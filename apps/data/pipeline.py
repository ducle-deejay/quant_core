"""Daily market data pipeline: DNSE ingest with Mirae backfill, a catalog check, and their launchd schedule."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
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
from market_data.notify import DiscordWebhook
from market_data.notify import notify_or_log
from market_data.sources import ETLStageError
from market_data.sources.mirae.load import FULL_DAY_BARS


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "data" / "catalog"
DNSE_RAW_ROOT = ROOT / "data" / "raw" / "vietnam" / "dnse"
MIRAE_RAW_ROOT = ROOT / "data" / "raw" / "vietnam" / "mirae"
LOG_DIR = ROOT / "data" / "logs"
SYMBOL = "VN30F1M"
DNSE_REQUEST_DELAY_SECONDS = 0.02
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

INGEST_AFTER = time(16, 0)
RUN_TIMES = tuple(time(hour, 0) for hour in range(16, 21))  # each run ingests only missing days, so later runs retry
CHECK_AT = time(21, 0)  # after the last run
CATCH_UP_TRADING_DAYS = 5
INGEST_LABEL = "io.quant-core.daily-data-etl"
CHECK_LABEL = "io.quant-core.daily-data-check"
INGEST_ERROR_LOG = LOG_DIR / "daily-etl.err.log"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("ingest", "check", "schedule"))
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    if args.command == "schedule":
        schedule()
        return
    webhook_url = os.getenv("DATA_DISCORD_WEBHOOK_URL", "").strip()
    notifier = DiscordWebhook(webhook_url) if webhook_url else None
    now = datetime.now(LOCAL_TIMEZONE)
    command = ingest if args.command == "ingest" else check
    sys.exit(command(notifier, now, args.date))


def ingest(notifier: DiscordWebhook | None, now: datetime, day: date | None) -> int:
    attempt = run_attempt(None if day else now, RUN_TIMES)
    api_key, api_secret = os.getenv("API_KEY", ""), os.getenv("API_SECRET", "")
    if not api_key or not api_secret:
        error = RuntimeError("API_KEY and API_SECRET must be defined in .env")
        notify_or_log(notifier, alert_startup_failed(error, str(INGEST_ERROR_LOG)), raise_on_error=True)
        print(f"STARTUP FAILED: {error}", file=sys.stderr)
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
            failure = ETLStageError(source="Pipeline", stage="day selection", cause=error)
            alert = alert_failed("Data pipeline", failure, attempt, str(INGEST_ERROR_LOG))
            notify_or_log(notifier, alert, raise_on_error=True)
            print(json.dumps({"day": now.date().isoformat(), "failed": str(error)}, indent=2, sort_keys=True))
            return 1
        if not days:
            print(f"{now.date()}: the catalog holds every recent trading day")
            return 0

    failed = False
    for current in days:
        try:
            report = run_and_alert(
                day=current,
                run_dnse=dnse_runner(client_factory, DNSE_RAW_ROOT, CATALOG_PATH, SYMBOL, DNSE_REQUEST_DELAY_SECONDS),
                run_mirae=mirae_runner(MIRAE_RAW_ROOT, DNSE_RAW_ROOT, CATALOG_PATH, SYMBOL),
                consolidate=catalog_consolidator(CATALOG_PATH),
                notifier=notifier,
                attempt=attempt,
                log_path=str(INGEST_ERROR_LOG),
                raise_on_error=True,
            )
        except Exception as error:
            print(json.dumps({"day": current.isoformat(), "failed": str(error)}, indent=2, sort_keys=True))
            failed = True
            continue
        print(json.dumps(_slim_report(report), indent=2, sort_keys=True))
    return 1 if failed else 0


def check(notifier: DiscordWebhook | None, now: datetime, day: date | None) -> int:
    """Alert for each recent trading day the catalog does not fully hold."""
    try:
        days = [day] if day else recent_trading_days(
            read_working_dates(DNSE_RAW_ROOT), now, INGEST_AFTER, CATCH_UP_TRADING_DAYS,
        )
    except Exception as error:
        # A check that cannot decide which days to read must still alert
        print(f"daily data check: {type(error).__name__}: {error}", file=sys.stderr)
        notify_or_log(notifier, _missing_alert(day or now.date(), None, error))
        return 1

    missing = False
    for current in days:
        counts: tuple[int, int, int] | None = None
        read_error: Exception | None = None
        try:
            counts = count_day_records(CATALOG_PATH, current)
        except Exception as error:
            print(f"daily data check {current}: {type(error).__name__}: {error}", file=sys.stderr)
            read_error = error
        if counts is not None:
            bars, trades, depth = counts
            print(f"daily data check {current}: {bars}/{FULL_DAY_BARS} bars, {trades} trades, {depth} depth rows")
            if bars >= FULL_DAY_BARS and trades and depth:
                continue
        notify_or_log(notifier, _missing_alert(current, counts, read_error))
        print(f"DATA MISSING for {current}", file=sys.stderr)
        missing = True
    return 1 if missing else 0


def schedule() -> None:
    """Install the ingest and check jobs as macOS LaunchAgents."""
    jobs = {
        INGEST_LABEL: ("ingest", [(at.hour, at.minute) for at in RUN_TIMES], "daily-etl"),
        CHECK_LABEL: ("check", [(CHECK_AT.hour, CHECK_AT.minute)], "daily-data-check"),
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for label, (command, times, log_name) in jobs.items():
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
            "StandardOutPath": str(LOG_DIR / f"{log_name}.out.log"),
            "StandardErrorPath": str(LOG_DIR / f"{log_name}.err.log"),
            "EnvironmentVariables": {
                "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
                "PYTHONUNBUFFERED": "1",
            },
            "ProcessType": "Background",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(payload))
        subprocess.run(["launchctl", "unload", str(path)], check=False, capture_output=True)
        subprocess.run(["launchctl", "load", str(path)], check=True)
        print(f"installed {path}")


def _missing_alert(day: date, counts: tuple[int, int, int] | None, error: Exception | None):
    fix = f"`.venv/bin/python3 apps/data/pipeline.py ingest --date {day}`"
    return alert_data_missing(day, counts, error, len(RUN_TIMES), fix, str(INGEST_ERROR_LOG))


def _slim_report(report: dict[str, object]) -> dict[str, object]:
    """Drop the per-bar timestamp lists from the printed report."""
    slim = json.loads(json.dumps(report, default=str))
    for source in ("dnse", "mirae"):
        section = slim.get(source)
        if isinstance(section, dict):
            section.pop("missing_bar_timestamps", None)
            section.get("records", {}).pop("added_bar_timestamps", None)
    return slim


if __name__ == "__main__":
    main()
