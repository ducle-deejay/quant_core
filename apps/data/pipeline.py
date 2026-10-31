"""Daily market data pipeline: DNSE ingest with Mirae backfill, a catalog audit, and their launchd schedule."""

from __future__ import annotations

import argparse
import logging
import os
import plistlib
import subprocess
import sys
import time as time_module
from datetime import date
from datetime import datetime
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from market_data.daily import alert_data_missing
from market_data.daily import alert_failed
from market_data.daily import alert_startup_failed
from market_data.daily import catalog_consolidator
from market_data.daily import count_day_records
from market_data.daily import days_to_ingest
from market_data.daily import dnse_client_factory
from market_data.daily import dnse_runner
from market_data.daily import mirae_runner
from market_data.daily import read_working_dates
from market_data.daily import recent_trading_days
from market_data.daily import record_working_dates
from market_data.daily import run_and_alert
from market_data.daily import run_attempt
from market_data.logs import configure as configure_logging
from market_data.logs import fields
from market_data.notify import DiscordWebhook
from market_data.notify import notify_or_log
from market_data.sources import ETLStageError
from market_data.sources.mirae.load import FULL_DAY_BARS


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
DATA_ROOT = Path(os.environ["DATA_ROOT"])
CATALOG_PATH = DATA_ROOT / "catalog"
DNSE_RAW_ROOT = DATA_ROOT / "raw" / "vietnam" / "dnse"
MIRAE_RAW_ROOT = DATA_ROOT / "raw" / "vietnam" / "mirae"
LOG_DIR = DATA_ROOT / "logs"
LAUNCHD_LOG_DIR = LOG_DIR / "launchd"
SYMBOL = "VN30F1M"
DNSE_REQUEST_DELAY_SECONDS = 0.02
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

INGEST_AFTER = time(16, 0)
RUN_TIMES = tuple(time(hour, 0) for hour in range(16, 21))  # each run ingests only missing days, so later runs retry
AUDIT_AT = time(21, 0)  # after the last run
CATCH_UP_TRADING_DAYS = 5
INGEST_LABEL = "io.quant-core.daily-data-ingest"
AUDIT_LABEL = "io.quant-core.daily-data-audit"
logger = logging.getLogger("Pipeline")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("ingest", "audit", "schedule"))
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    if args.command == "schedule":
        schedule()
        return
    now = datetime.now(LOCAL_TIMEZONE)
    log_path = configure_logging(LOG_DIR, args.command, now.date())
    webhook_url = os.getenv("DATA_DISCORD_WEBHOOK_URL", "").strip()
    notifier = DiscordWebhook(webhook_url) if webhook_url else None
    command = ingest if args.command == "ingest" else audit
    sys.exit(command(notifier, now, args.date, log_path))


def ingest(notifier: DiscordWebhook | None, now: datetime, day: date | None, log_path: Path) -> int:
    attempt = run_attempt(None if day else now, RUN_TIMES)
    started = time_module.monotonic()
    logger.info("run started %s", fields(attempt=attempt.label, requested_day=day or "auto"))
    api_key, api_secret = os.getenv("API_KEY", ""), os.getenv("API_SECRET", "")
    if not api_key or not api_secret:
        error = RuntimeError("API_KEY and API_SECRET must be defined in .env")
        logger.error("startup failed %s", fields(error=error))
        notify_or_log(notifier, alert_startup_failed(error, str(log_path)), raise_on_error=True)
        return 1
    client_factory = dnse_client_factory(api_key, api_secret)

    if day:
        days = [day]
    else:
        try:
            days = days_to_ingest(
                catalog_path=CATALOG_PATH,
                working_dates=record_working_dates(DNSE_RAW_ROOT, client_factory),
                now=now,
                ingest_after=INGEST_AFTER,
                count=CATCH_UP_TRADING_DAYS,
            )
        except Exception as error:
            logger.exception("day selection failed %s", fields(error=f"{type(error).__name__}: {error}"))
            failure = ETLStageError(source="Pipeline", stage="day selection", cause=error)
            notify_or_log(notifier, alert_failed("Data pipeline", failure, attempt, str(log_path)), raise_on_error=True)
            return 1
    logger.info("days to ingest %s", fields(days=",".join(str(current) for current in days) or "none"))

    ingested = failed = 0
    for current in days:
        try:
            run_and_alert(
                day=current,
                run_dnse=dnse_runner(client_factory, DNSE_RAW_ROOT, CATALOG_PATH, SYMBOL, DNSE_REQUEST_DELAY_SECONDS),
                run_mirae=mirae_runner(MIRAE_RAW_ROOT, DNSE_RAW_ROOT, CATALOG_PATH, SYMBOL),
                consolidate=catalog_consolidator(CATALOG_PATH),
                notifier=notifier,
                attempt=attempt,
                log_path=str(log_path),
                raise_on_error=True,
            )
        except Exception:
            failed += 1
            continue
        ingested += 1
    logger.info(
        "run finished %s",
        fields(attempt=attempt.label, duration_min=f"{(time_module.monotonic() - started) / 60:.1f}", ingested=ingested, failed=failed),
    )
    return 1 if failed else 0


def audit(notifier: DiscordWebhook | None, now: datetime, day: date | None, log_path: Path) -> int:
    """Alert for each recent trading day the catalog does not fully hold."""
    audit_logger = logging.getLogger("Catalog.audit")
    logger.info("run started %s", fields(requested_day=day or "auto"))
    try:
        days = [day] if day else recent_trading_days(
            read_working_dates(DNSE_RAW_ROOT), now, INGEST_AFTER, CATCH_UP_TRADING_DAYS,
        )
    except Exception as error:
        # An audit that cannot decide which days to read must still alert
        audit_logger.exception("day selection failed %s", fields(error=f"{type(error).__name__}: {error}"))
        notify_or_log(notifier, _missing_alert(day or now.date(), None, error, log_path))
        return 1

    complete = missing = 0
    for current in days:
        counts: tuple[int, int, int] | None = None
        read_error: Exception | None = None
        try:
            counts = count_day_records(CATALOG_PATH, current)
        except Exception as error:
            audit_logger.exception("catalog read failed %s", fields(day=current, error=f"{type(error).__name__}: {error}"))
            read_error = error
        if counts is not None:
            bars, trades, depth = counts
            values = fields(day=current, bars=f"{bars}/{FULL_DAY_BARS}", trades=trades, order_book_rows=depth)
            if bars >= FULL_DAY_BARS and trades and depth:
                audit_logger.info("day complete %s", values)
                complete += 1
                continue
            audit_logger.error("day incomplete %s", values)
        notify_or_log(notifier, _missing_alert(current, counts, read_error, log_path))
        missing += 1
    logger.info("run finished %s", fields(complete=complete, missing=missing))
    return 1 if missing else 0


def schedule() -> None:
    """Install the ingest and audit jobs as macOS LaunchAgents."""
    jobs = {
        INGEST_LABEL: ("ingest", [(at.hour, at.minute) for at in RUN_TIMES]),
        AUDIT_LABEL: ("audit", [(AUDIT_AT.hour, AUDIT_AT.minute)]),
    }
    LAUNCHD_LOG_DIR.mkdir(parents=True, exist_ok=True)
    for label, (command, times) in jobs.items():
        path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        payload = {
            "Label": label,
            "ProgramArguments": [sys.executable, str(Path(__file__).resolve()), command],
            # launchd.plist(5): Weekday takes one integer (1 = Monday), so each weekday is its own interval
            "StartCalendarInterval": [
                {"Hour": hour, "Minute": minute, "Weekday": weekday}
                for weekday in range(1, 6)
                for hour, minute in times
            ],
            "WorkingDirectory": str(ROOT),
            "StandardOutPath": str(LAUNCHD_LOG_DIR / f"{command}.out.log"),
            "StandardErrorPath": str(LAUNCHD_LOG_DIR / f"{command}.err.log"),
            "EnvironmentVariables": {
                "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
                "PYTHONUNBUFFERED": "1",
            },
            "ProcessType": "Standard",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(payload))
        subprocess.run(["launchctl", "unload", str(path)], check=False, capture_output=True)
        subprocess.run(["launchctl", "load", str(path)], check=True)
        print(f"installed {path}")


def _missing_alert(day: date, counts: tuple[int, int, int] | None, error: Exception | None, log_path: Path):
    fix = f"`.venv/bin/python3 apps/data/pipeline.py ingest --date {day}`"
    return alert_data_missing(day, counts, error, len(RUN_TIMES), fix, str(log_path))


if __name__ == "__main__":
    main()
