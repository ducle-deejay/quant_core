"""Trading alert formatter tests (governing note DEC-012): unified template
with icons, VN timestamps, and HTML-escaped dynamic values."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from trading.notify import format_flatten_failed  # noqa: E402
from trading.notify import format_force_close  # noqa: E402
from trading.notify import format_order_outcome  # noqa: E402
from trading.notify import format_risk_state  # noqa: E402
from trading.notify import format_session  # noqa: E402


def test_format_session():
    message = format_session("session starting | VN30F1M.HNX")
    assert message.startswith("📈 QC-TRADING PAPER | ")
    assert "session starting | VN30F1M.HNX" in message


def test_format_order_outcome():
    message = format_order_outcome("REJECTED", client_order_id="QC-1", reason="X<Y")
    assert "⚠️ QC-TRADING PAPER | " in message
    assert "ORDER REJECTED" in message
    assert "coid QC-1 · reason X&lt;Y" in message  # HTML-escaped
    assert "<code>" in message


def test_format_order_outcome_without_reason():
    message = format_order_outcome("DENIED", client_order_id="QC-2")
    assert "ORDER DENIED" in message
    assert "reason" not in message


def test_format_force_close():
    message = format_force_close(-2, time="14:00")
    assert "🛑 QC-TRADING PAPER | " in message
    assert "FORCE CLOSE" in message
    assert "position -2 → flat · cut 14:00" in message


def test_format_risk_state():
    message = format_risk_state("ACTIVE", "HALTED", "loss_limit")
    assert "🚨 QC-TRADING PAPER | " in message
    assert "RISK STATE" in message
    assert "ACTIVE → HALTED · loss_limit" in message


def test_format_flatten_failed():
    message = format_flatten_failed("VN30F1M.HNX", 3)
    assert "🔴 QC-TRADING PAPER | " in message
    assert "FLATTEN FAILED" in message
    assert "VN30F1M.HNX · attempts 3" in message


def _run_all() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as error:
                failures += 1
                print(f"FAIL {name}: {error}")
            except Exception as error:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {type(error).__name__}: {error}")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _run_all() else 0)
