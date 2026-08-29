"""Daily ETL entrypoint: DNSE primary + Mirae candlestick fallback + Telegram.

Usage (from the repo root, project venv):

    API_KEY=... API_SECRET=... \\
    TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... \\
    .venv/bin/python3 apps/data/daily/pipeline.py [--date YYYY-MM-DD]

Exits non-zero when both sources failed or bars remain missing after the
Mirae backfill; the Telegram alert carries the failure detail.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from market_data.daily import dnse_runner
from market_data.daily import load_json_config
from market_data.daily import mirae_runner
from market_data.daily import run_and_alert
from market_data.notify import notifier_from_env


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONFIG = HERE / "config" / "pipeline.json"
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the daily DNSE + Mirae data pipelines")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    config = load_json_config(args.config)
    dnse_config = load_json_config(_resolve(args.config.parent, config["dnse_config"]))
    mirae_config = load_json_config(_resolve(args.config.parent, config["mirae_config"]))
    day = args.date or datetime.now(LOCAL_TIMEZONE).date()

    notifier = notifier_from_env()
    report = run_and_alert(
        day=day,
        run_dnse=dnse_runner(dnse_config),
        run_mirae=mirae_runner(mirae_config, dnse_config),
        notifier=notifier,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


def _resolve(anchor: Path, value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else anchor / path


if __name__ == "__main__":
    main()
