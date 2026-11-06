"""Daily market data pipeline: DNSE ingest cleaned against the reference brokers, a catalog audit against the exchange, and their launchd schedule."""

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

from dotenv import load_dotenv

from market_data import LOCAL_TIMEZONE
from market_data.daily import FULL_DAY_BARS
from market_data.daily import alert_brokers_differ
from market_data.daily import alert_data_missing
from market_data.daily import alert_exchange_mismatch
from market_data.daily import alert_exchange_unchecked
from market_data.daily import alert_failed
from market_data.daily import alert_startup_failed
from market_data.daily import broker_exchange_gaps
from market_data.daily import broker_runner
from market_data.daily import catalog_consolidator
from market_data.daily import catalog_day_summary
from market_data.daily import count_day_records
from market_data.daily import day_is_complete
from market_data.daily import days_to_ingest
from market_data.daily import dnse_client_factory
from market_data.daily import dnse_runner
from market_data.daily import exchange_gaps
from market_data.daily import publish_catalog
from market_data.daily import read_working_dates
from market_data.daily import recent_trading_days
from market_data.daily import record_working_dates
from market_data.daily import run_and_alert
from market_data.daily import run_attempt
from market_data.logs import configure as configure_logging
from market_data.logs import fields
from market_data.logs import stage
from market_data.notify import DiscordWebhook
from market_data.notify import send_alert
from market_data.sources import ETLStageError
from market_data.sources.hnx.extract import extract_day as extract_exchange_day
from market_data.sources.hnx.extract import front_contract


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
DATA_ROOT = Path(os.environ["DATA_ROOT"])
CATALOG_PATH = DATA_ROOT / "catalog"
PUBLISHED_ROOT = DATA_ROOT / "published"
DNSE_RAW_ROOT = DATA_ROOT / "raw" / "vietnam" / "dnse"
BROKER_RAW_ROOT = DATA_ROOT / "raw" / "vietnam"
HNX_RAW_ROOT = DATA_ROOT / "raw" / "vietnam" / "hnx"
LOG_DIR = DATA_ROOT / "logs"
LAUNCHD_LOG_DIR = LOG_DIR / "launchd"
SYMBOL = "VN30F1M"
DNSE_REQUEST_DELAY_SECONDS = 0.02

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
        send_alert(notifier, alert_startup_failed(error, str(log_path)), raise_on_error=True)
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
            send_alert(notifier, alert_failed("Data pipeline", failure, attempt, str(log_path)), raise_on_error=True)
            return 1
    logger.info("days to ingest %s", fields(days=",".join(str(current) for current in days) or "none"))

    ingested = failed = 0
    for current in days:
        try:
            run_and_alert(
                day=current,
                run_brokers=broker_runner(BROKER_RAW_ROOT),
                run_dnse=dnse_runner(client_factory, DNSE_RAW_ROOT, CATALOG_PATH, SYMBOL, DNSE_REQUEST_DELAY_SECONDS),
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

    published = False
    if ingested and not failed:
        try:
            with stage("Catalog", "publish", now.date()):
                publish_catalog(CATALOG_PATH, PUBLISHED_ROOT)
            published = True
        except ETLStageError as error:
            send_alert(notifier, alert_failed("Catalog publish", error, attempt, str(log_path)), raise_on_error=True)
    logger.info(
        "run finished %s",
        fields(
            attempt=attempt.label,
            duration_min=f"{(time_module.monotonic() - started) / 60:.1f}",
            ingested=ingested,
            failed=failed,
            published=published,
        ),
    )
    return 1 if failed or (ingested and not published) else 0


def audit(notifier: DiscordWebhook | None, now: datetime, day: date | None, log_path: Path) -> int:
    """Alert for each recent trading day the catalog does not hold, or that differs from the HNX daily results.

    A day is compared with the exchange once, when its HNX results are first retained; ``--date`` compares again.
    """
    audit_logger = logging.getLogger("Catalog.audit")
    logger.info("run started %s", fields(requested_day=day or "auto"))
    try:
        days = [day] if day else recent_trading_days(
            read_working_dates(DNSE_RAW_ROOT), now, INGEST_AFTER, CATCH_UP_TRADING_DAYS,
        )
    except Exception as error:
        # An audit that cannot decide which days to read must still alert
        audit_logger.exception("day selection failed %s", fields(error=f"{type(error).__name__}: {error}"))
        send_alert(notifier, _missing_alert(day or now.date(), None, error, log_path))
        return 1

    matched = missing = differs = unchecked = 0
    for current in days:
        counts: tuple[int, int, int] | None = None
        read_error: Exception | None = None
        try:
            counts = count_day_records(CATALOG_PATH, current)
        except Exception as error:
            audit_logger.exception("catalog read failed %s", fields(day=current, error=f"{type(error).__name__}: {error}"))
            read_error = error
        if counts is None or not day_is_complete(CATALOG_PATH, current):
            if counts is not None:
                bars, trades, depth = counts
                audit_logger.error("day not ingested %s", fields(day=current, bars=f"{bars}/{FULL_DAY_BARS}", trades=trades, order_book_rows=depth))
            send_alert(notifier, _missing_alert(current, counts, read_error, log_path))
            missing += 1
            if counts is None or counts[0] == 0:
                continue
        if day is None and (HNX_RAW_ROOT / f"{current.isoformat()}.html").exists():
            continue
        try:
            raw = extract_exchange_day(raw_root=HNX_RAW_ROOT, day=current)
            if raw is None:
                reason = "HNX has not published the day"
            else:
                exchange = front_contract(raw)
                reason = None if exchange.has_values else "HNX results are incomplete"
        except Exception as error:
            audit_logger.exception("exchange read failed %s", fields(day=current, error=f"{type(error).__name__}: {error}"))
            reason = f"{type(error).__name__}: {error}"
        if reason:
            audit_logger.warning("day not checked %s", fields(day=current, reason=reason))
            send_alert(notifier, alert_exchange_unchecked(current, reason, str(log_path)))
            unchecked += 1
            continue
        catalog = catalog_day_summary(CATALOG_PATH, current)
        gaps = exchange_gaps(catalog, exchange)
        values = fields(day=current, bars=f"{int(catalog['bars'])}/{FULL_DAY_BARS}", contract=exchange.symbol, **{f"{key}_gap": value for key, value in gaps.items()})
        if gaps:
            audit_logger.warning("day differs from the exchange %s", values)
            send_alert(notifier, alert_exchange_mismatch(current, catalog, exchange, gaps, str(log_path)))
            differs += 1
        else:
            audit_logger.info("day matches the exchange %s", values)
            matched += 1
        try:
            brokers = broker_exchange_gaps(BROKER_RAW_ROOT, current, exchange)
        except Exception as error:
            audit_logger.exception("broker read failed %s", fields(day=current, error=f"{type(error).__name__}: {error}"))
            brokers = {"brokers": f"{type(error).__name__}: {error}"}
        for name, value in brokers.items():
            detail = {"reason": value} if isinstance(value, str) else {f"{field}_gap": gap for field, gap in value.items()}
            audit_logger.warning("broker differs from the exchange %s", fields(day=current, broker=name, **detail))
        if brokers:
            send_alert(notifier, alert_brokers_differ(current, brokers, str(log_path)))
    logger.info("run finished %s", fields(matched=matched, differs=differs, unchecked=unchecked, missing=missing))
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
