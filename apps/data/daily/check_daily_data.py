"""Daily data check: alerts for each recent trading day the catalog does not fully hold.
Exits 1 when data is missing, 0 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from market_data.daily import alert_data_missing
from market_data.daily import count_day_records
from market_data.daily import load_json_config
from market_data.daily import read_working_dates
from market_data.daily import recent_trading_days
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

    now = datetime.now(LOCAL_TIMEZONE)
    notifier = data_notifier_from_env()
    try:
        dnse_config = load_json_config(_resolve(load_json_config(args.config)["dnse_config"]))
        catalog_path = _resolve(dnse_config["catalog_path"])
        if args.date:
            days = [args.date]
        else:
            days = recent_trading_days(read_working_dates(_resolve(dnse_config["raw_root"])), now)
    except Exception as error:
        # A check that cannot decide which days to read must still alert
        print(f"daily data check: {type(error).__name__}: {error}", file=sys.stderr)
        notify_or_log(notifier, alert_data_missing(args.date or now.date(), None, error))
        sys.exit(1)

    missing = False
    for day in days:
        counts: tuple[int, int, int] | None = None
        read_error: Exception | None = None
        try:
            counts = count_day_records(catalog_path, day)
        except Exception as error:
            print(f"daily data check {day}: {type(error).__name__}: {error}", file=sys.stderr)
            read_error = error
        if counts is not None:
            bars, trades, depth = counts
            print(f"daily data check {day}: {bars}/{FULL_DAY_BARS} bars, {trades} trades, {depth} depth rows")
            if bars >= FULL_DAY_BARS and trades and depth:
                continue
        notify_or_log(notifier, alert_data_missing(day, counts, read_error))
        print(f"DATA MISSING for {day}", file=sys.stderr)
        missing = True
    if missing:
        sys.exit(1)


def _resolve(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    main()
