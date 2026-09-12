"""Daily ETL entrypoint: DNSE primary + Mirae candlestick fallback + Telegram.
Usage (repo root): set API_KEY/API_SECRET/TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID,
then ``.venv/bin/python3 apps/data/daily/pipeline.py [--date YYYY-MM-DD]``.
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

from market_data.daily import alert_bootstrap_failure
from market_data.daily import dnse_runner
from market_data.daily import load_json_config
from market_data.daily import mirae_runner
from market_data.daily import run_and_alert
from market_data.heartbeat import write_status
from market_data.notify import data_notifier_from_env
from market_data.notify import notify_or_log


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
    - Every run writes a heartbeat status file (``market_data.heartbeat``)
      that the io.quant-core.daily-etl-watch LaunchAgent checks for missed
      runs; exits non-zero when both sources failed or bars remain missing
      after the Mirae backfill.
    """
    parser = argparse.ArgumentParser(description="Run the daily DNSE + Mirae data pipelines")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    day = args.date or datetime.now(LOCAL_TIMEZONE).date()

    # The notifier is built before anything that can fail: config-load crashes
    # must still reach Telegram (DEC-012).
    notifier = data_notifier_from_env()

    # Bootstrap phase: config resolution. Any error here previously died
    # silently before the notifier existed (OBS-013); now it alerts loudly.
    try:
        config = load_json_config(args.config)
        dnse_config = load_json_config(_resolve(config["dnse_config"]))
        mirae_config = load_json_config(_resolve(config["mirae_config"]))
    except Exception as error:
        notify_or_log(
            notifier,
            alert_bootstrap_failure(day, error),
            raise_on_error=True,
        )
        print(f"STARTUP FAILED: {error}", file=sys.stderr)
        write_status(day, result=f"failed: {error}")
        sys.exit(1)

    write_status(day, result="running")

    try:
        report = run_and_alert(
            day=day,
            run_dnse=dnse_runner(dnse_config),
            run_mirae=mirae_runner(mirae_config, dnse_config),
            notifier=notifier,
            raise_on_error=True,
        )
    except Exception as error:
        print(json.dumps({"day": day.isoformat(), "failed": str(error)}, indent=2, sort_keys=True))
        write_status(day, result=f"failed: {error}")
        sys.exit(1)

    write_status(day, result="ok")
    print(json.dumps(_slim_report(report), indent=2, sort_keys=True))


def _slim_report(report: dict[str, object]) -> dict[str, object]:
    """Strip huge per-bar timestamp arrays from the printed report (the full
    report stays available programmatically for the acceptance layers)."""
    slim = copy.deepcopy(report)
    for source in ("dnse", "mirae"):
        section = slim.get(source)
        if isinstance(section, dict):
            section.pop("missing_bar_timestamps", None)
            section.pop("added_bar_timestamps", None)
    return slim


def _resolve(value: object) -> Path:
    """Resolve a config path against the repo root (matches daily._resolve_path)."""
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    sys.exit(main())
