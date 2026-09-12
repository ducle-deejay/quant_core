"""Daily ETL heartbeat watcher: alerts RUN MISSING when today's 16:00 run never happened.
LaunchAgent io.quant-core.daily-etl-watch 16:10 Mon-Fri; exit 0 healthy, 1 missing.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from market_data.daily import format_run_missing
from market_data.heartbeat import check_status
from market_data.notify import data_notifier_from_env
from market_data.notify import notify_or_log


ROOT = Path(__file__).resolve().parents[2]
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def main() -> None:
    load_dotenv(ROOT / ".env")
    day = datetime.now(LOCAL_TIMEZONE).date()
    status, detail = check_status(day=day)
    print(f"heartbeat {status} for {day}: {detail}")
    if status != "missing":
        return
    notify_or_log(data_notifier_from_env(), format_run_missing(day))
    print(f"RUN MISSING: {detail}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
