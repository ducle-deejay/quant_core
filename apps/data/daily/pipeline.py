"""Daily ETL entrypoint: DNSE primary + Mirae candlestick fallback + Discord alerts.
Usage: .venv/bin/python3 apps/data/daily/pipeline.py [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import date
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from market_data.daily import alert_failed
from market_data.daily import alert_startup_failed
from market_data.daily import catalog_consolidator
from market_data.daily import days_to_ingest
from market_data.daily import dnse_runner
from market_data.daily import load_json_config
from market_data.daily import mirae_runner
from market_data.daily import record_working_dates
from market_data.daily import run_and_alert
from market_data.daily import run_attempt
from market_data.notify import data_notifier_from_env
from market_data.notify import notify_or_log
from market_data.sources import ETLStageError


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONFIG = HERE / "config" / "pipeline.json"
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def main() -> None:
    """Run the daily ETL with loud failure alerting.

    - The notifier is built FIRST: any failure before the run starts (config
      load, JSON decode, env) sends a STARTUP FAILED alert and exits non-zero.
    - The success/failure alert is sent with ``raise_on_error=True``: an
      undeliverable alert fails the run loudly instead of pretending success.
    - Without ``--date``, ingests every recent trading day the catalog does not
      fully hold, so a later scheduled run retries a failed day.
    - Exits non-zero when any day failed.
    """
    parser = argparse.ArgumentParser(description="Run the daily DNSE + Mirae data pipelines")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    now = datetime.now(LOCAL_TIMEZONE)
    day = args.date or now.date()
    attempt = run_attempt(None if args.date else now)

    # The notifier is built before anything that can fail: config-load crashes
    # must still be alerted.
    notifier = data_notifier_from_env()

    # Bootstrap phase: config resolution. Any error here sends a
    # STARTUP FAILED alert.
    try:
        config = load_json_config(args.config)
        dnse_config = load_json_config(_resolve(config["dnse_config"]))
        mirae_config = load_json_config(_resolve(config["mirae_config"]))
    except Exception as error:
        notify_or_log(
            notifier,
            alert_startup_failed(error),
            raise_on_error=True,
        )
        print(f"STARTUP FAILED: {error}", file=sys.stderr)
        sys.exit(1)

    if args.date:
        days = [args.date]
    else:
        try:
            days = days_to_ingest(
                catalog_path=_resolve(dnse_config["catalog_path"]),
                working_dates=record_working_dates(_resolve(dnse_config["raw_root"])),
                now=now,
            )
        except Exception as error:
            failure = ETLStageError(source="Pipeline", stage="day selection", cause=error)
            notify_or_log(notifier, alert_failed("Data pipeline", failure, attempt), raise_on_error=True)
            print(json.dumps({"day": day.isoformat(), "failed": str(error)}, indent=2, sort_keys=True))
            sys.exit(1)
        if not days:
            print(f"{day}: the catalog holds every recent trading day")
            return

    failed = False
    for day in days:
        try:
            report = run_and_alert(
                day=day,
                run_dnse=dnse_runner(dnse_config),
                run_mirae=mirae_runner(mirae_config, dnse_config),
                consolidate=catalog_consolidator(dnse_config),
                notifier=notifier,
                attempt=attempt,
                raise_on_error=True,
            )
        except Exception as error:
            print(json.dumps({"day": day.isoformat(), "failed": str(error)}, indent=2, sort_keys=True))
            failed = True
            continue
        print(json.dumps(_slim_report(report), indent=2, sort_keys=True))
    if failed:
        sys.exit(1)


def _slim_report(report: dict[str, object]) -> dict[str, object]:
    """Strip huge per-bar timestamp arrays from the printed report (the full
    report stays available to callers)."""
    slim = copy.deepcopy(report)
    for source in ("dnse", "mirae"):
        section = slim.get(source)
        if isinstance(section, dict):
            section.pop("missing_bar_timestamps", None)
            section.pop("added_bar_timestamps", None)
    return slim


def _resolve(value: object) -> Path:
    """Resolve a config path against the repo root."""
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    sys.exit(main())
