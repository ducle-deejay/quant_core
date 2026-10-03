"""Daily data check: alerts when the catalog holds fewer than a full session of bars for the day.
Exits 1 when bars are missing, 0 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from market_data.daily import count_day_bars
from market_data.daily import format_run_missing
from market_data.daily import load_json_config
from market_data.notify import data_notifier_from_env
from market_data.notify import notify_or_log
from market_data.sources.mirae.load import FULL_DAY_BARS


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONFIG = HERE / "config" / "pipeline.json"
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check that the catalog holds the day's bars")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    day = args.date or datetime.now(LOCAL_TIMEZONE).date()
    try:
        dnse_config = load_json_config(_resolve(load_json_config(args.config)["dnse_config"]))
        bars = count_day_bars(_resolve(dnse_config["catalog_path"]), day)
    except Exception as error:
        # A check that cannot read the catalog must still alert
        print(f"daily data check {day}: {type(error).__name__}: {error}", file=sys.stderr)
        bars = 0
    print(f"daily data check {day}: {bars}/{FULL_DAY_BARS} bars")
    if bars >= FULL_DAY_BARS:
        return
    notify_or_log(data_notifier_from_env(), format_run_missing(day))
    print(f"DATA MISSING: {bars}/{FULL_DAY_BARS} bars for {day}", file=sys.stderr)
    sys.exit(1)


def _resolve(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    main()
