"""Smoke-test every alert template end-to-end through the real Telegram
channels (DEC-012). Sends one message per format; any delivery failure
raises (exit non-zero). Run after configuring .env:

    .venv/bin/python3 apps/smoke_alerts.py
"""

from __future__ import annotations

import sys
from datetime import date
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from market_data.daily import alert_bootstrap_failure
from market_data.daily import alert_failure
from market_data.daily import alert_success
from market_data.daily import format_run_missing
from market_data.notify import data_notifier_from_env
from market_data.notify import notify_or_log
from market_data.notify import trading_notifier_from_env
from trading.notify import format_flatten_failed
from trading.notify import format_force_close
from trading.notify import format_order_outcome
from trading.notify import format_risk_state
from trading.notify import format_session

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 8, 28)

SAMPLE_REPORT = {
    "day": "2026-08-28",
    "dnse": {
        "records": {"Bar": 241, "TradeTick": 89565, "OrderBookDepth10": 593874},
        "missing_bar_timestamps": [],
    },
    "mirae": {"records": {"Bar": 0, "SkippedBar": 473773}, "added_bar_timestamps": []},
}


def main() -> int:
    load_dotenv(ROOT / ".env")
    data = data_notifier_from_env()
    trading = trading_notifier_from_env()
    if data is None or trading is None:
        print("Telegram channels not configured - fill .env first", file=sys.stderr)
        return 2

    messages: list[tuple[object, str]] = [
        (data, "DATA success: " + alert_success(DAY, SAMPLE_REPORT)),
        (data, "DATA failure: " + alert_failure(DAY, RuntimeError("DNSE daily pipeline failed; Mirae backup also failed"), None)),
        (data, "DATA bootstrap: " + alert_bootstrap_failure(DAY, FileNotFoundError("config/pipeline.json"))),
        (data, "DATA heartbeat: " + format_run_missing(DAY)),
        (trading, "TRADING session: " + format_session("session starting | VN30F1M.HNX")),
        (trading, "TRADING reject: " + format_order_outcome("REJECTED", client_order_id="QC-123", reason="INSUFFICIENT_MARGIN")),
        (trading, "TRADING force close: " + format_force_close(-2, time="14:00")),
        (trading, "TRADING risk: " + format_risk_state("ACTIVE", "HALTED", "loss_limit")),
        (trading, "TRADING flatten: " + format_flatten_failed("VN30F1M.HNX", 3)),
    ]

    failures = 0
    for notifier, text in messages:
        try:
            notify_or_log(notifier, text, raise_on_error=True)
            print(f"sent: {text.splitlines()[0]}")
        except Exception as error:  # noqa: BLE001 - smoke must report every failure
            failures += 1
            print(f"FAILED ({type(error).__name__}): {error}", file=sys.stderr)
    print(f"smoke done: {len(messages) - failures}/{len(messages)} delivered")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
