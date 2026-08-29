"""Pure-helper tests for the bridge strategy (workstream B, DEC-008).

Tests are derived from the decision rules in the bridge module and the
``trading.contracts`` protocols; governing notes: DEC-008 (live wiring
architecture), STG-6-TRADE-SCHEDULING design intent. No node execution, no
credentials: only pure helpers and import-time construction are exercised.

Runs under pytest when available, and also as a plain assert runner:

    .venv/bin/python3 src/trading/tests/test_bridge.py
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from zoneinfo import ZoneInfo

from nautilus_trader.model.identifiers import ClientOrderId
from nautilus_trader.trading.strategy import Strategy

from trading.contracts import RiskState
from trading.contracts import TargetPosition
from trading.strategies.bridge import BridgeConfig
from trading.strategies.bridge import BridgeStrategy
from trading.strategies.bridge import VN_TZ
from trading.strategies.bridge import bar_period_timedelta
from trading.strategies.bridge import client_order_id_for
from trading.strategies.bridge import has_working_orders
from trading.strategies.bridge import is_below_min_gap
from trading.strategies.bridge import is_cooldown_elapsed
from trading.strategies.bridge import order_side_for_delta
from trading.strategies.bridge import should_force_close
from trading.strategies.bridge import target_delta
from trading.strategies.bridge import warmup_start

UTC = timezone.utc
VN = ZoneInfo("Asia/Ho_Chi_Minh")


def _vn(y: int, m: int, d: int, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=VN)


# --------------------------------------------------------------------------- #
# should_force_close boundaries
# --------------------------------------------------------------------------- #


def test_should_force_close_before_cutoff():
    assert not should_force_close(_vn(2026, 9, 1, 13, 59, 59), "14:00", VN_TZ)


def test_should_force_close_at_cutoff():
    assert should_force_close(_vn(2026, 9, 1, 14, 0, 0), "14:00", VN_TZ)


def test_should_force_close_after_cutoff():
    assert should_force_close(_vn(2026, 9, 1, 14, 30, 0), "14:00", VN_TZ)


def test_should_force_close_before_market_open():
    assert not should_force_close(_vn(2026, 9, 1, 9, 0, 0), "14:00", VN_TZ)


def test_should_force_close_day_rollover():
    # Same cutoff each local day: day 1 after close, day 2 morning, day 2 after close.
    assert should_force_close(_vn(2026, 9, 1, 15, 0, 0), "14:00", VN_TZ)
    assert not should_force_close(_vn(2026, 9, 2, 9, 0, 0), "14:00", VN_TZ)
    assert should_force_close(_vn(2026, 9, 2, 14, 1, 0), "14:00", VN_TZ)


def test_should_force_close_utc_input_converted_to_vn():
    # 14:00 VN == 07:00 UTC.
    utc_ts = datetime(2026, 9, 1, 7, 0, 0, tzinfo=UTC)
    assert should_force_close(utc_ts, "14:00", VN_TZ)
    utc_ts_before = datetime(2026, 9, 1, 6, 59, 59, tzinfo=UTC)
    assert not should_force_close(utc_ts_before, "14:00", VN_TZ)


def test_should_force_close_rejects_naive_timestamp():
    try:
        should_force_close(datetime(2026, 9, 1, 14, 0, 0), "14:00", VN_TZ)
    except ValueError:
        return
    raise AssertionError("naive timestamp must raise ValueError")


def test_should_force_close_rejects_bad_time_string():
    for bad in ("25:00", "14", "abc", "", "14:00:00"):
        try:
            should_force_close(_vn(2026, 9, 1, 14, 0), bad, VN_TZ)
        except ValueError:
            continue
        raise AssertionError(f"bad time string {bad!r} must raise ValueError")


def test_should_force_close_custom_cutoff():
    assert not should_force_close(_vn(2026, 9, 1, 14, 44, 59), "14:45", VN_TZ)
    assert should_force_close(_vn(2026, 9, 1, 14, 45, 0), "14:45", VN_TZ)
    assert should_force_close(_vn(2026, 9, 1, 14, 45, 1), "14:45", VN_TZ)


# --------------------------------------------------------------------------- #
# delta / gap / cooldown / stacking decisions
# --------------------------------------------------------------------------- #


def test_target_delta_values():
    assert target_delta(3, 1) == 2
    assert target_delta(-2, 1) == -3
    assert target_delta(0, 0) == 0
    assert target_delta(0, 4) == -4


def test_is_below_min_gap_boundaries():
    assert is_below_min_gap(0, 1)  # no change with min gap 1 -> skip
    assert not is_below_min_gap(1, 1)  # 1-lot change with min gap 1 -> trade
    assert not is_below_min_gap(-1, 1)
    assert is_below_min_gap(1, 2)  # 1-lot change with min gap 2 -> skip
    assert not is_below_min_gap(2, 2)
    assert not is_below_min_gap(-2, 2)


def test_is_cooldown_elapsed():
    assert is_cooldown_elapsed(None, 1_000, 5.0)  # never submitted
    now = 100_000_000_000
    assert is_cooldown_elapsed(now - 5_000_000_000, now, 5.0)  # exactly at cooldown
    assert is_cooldown_elapsed(now - 6_000_000_000, now, 5.0)  # past cooldown
    assert not is_cooldown_elapsed(now - 4_999_999_999, now, 5.0)  # inside cooldown
    assert not is_cooldown_elapsed(now - 1, now, 5.0)  # submitted just now


def test_has_working_orders():
    assert not has_working_orders(0, 0)
    assert has_working_orders(1, 0)
    assert has_working_orders(0, 1)
    assert has_working_orders(2, 1)


def test_order_side_for_delta():
    assert order_side_for_delta(2) == "BUY"
    assert order_side_for_delta(-3) == "SELL"
    try:
        order_side_for_delta(0)
    except ValueError:
        return
    raise AssertionError("zero delta must raise ValueError")


# --------------------------------------------------------------------------- #
# deterministic client order id / warmup window
# --------------------------------------------------------------------------- #


def test_client_order_id_for_is_deterministic_and_valid():
    value = client_order_id_for("bridge", 1725184800000000000)
    assert value == "bridge-1725184800000000000"
    assert client_order_id_for("bridge", 1725184800000000000) == value
    # Must be a valid Nautilus ClientOrderId (non-empty ASCII).
    assert ClientOrderId(value).value == value


def test_bar_period_timedelta():
    assert bar_period_timedelta("VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL") == timedelta(minutes=1)
    assert bar_period_timedelta("VN30F1M.HNX-5-MINUTE-LAST-EXTERNAL") == timedelta(minutes=5)
    assert bar_period_timedelta("VN30F1M.HNX-1-HOUR-LAST-EXTERNAL") == timedelta(hours=1)
    assert bar_period_timedelta("VN30F1M.HNX-1-DAY-LAST-EXTERNAL") == timedelta(days=1)
    try:
        bar_period_timedelta("VN30F1M.HNX-1-TICK-LAST-EXTERNAL")
    except ValueError:
        return
    raise AssertionError("unsupported aggregation must raise ValueError")


def test_warmup_start_window():
    now = datetime(2026, 9, 1, 3, 0, 0, tzinfo=UTC)
    start = warmup_start(now, "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL", 800)
    # 800 bars x 1 min x calendar multiple 2.0.
    assert start == now - timedelta(minutes=1600)
    assert start.tzinfo is not None


def test_warmup_start_rejects_naive_now():
    try:
        warmup_start(datetime(2026, 9, 1, 3, 0, 0), "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL", 800)
    except ValueError:
        return
    raise AssertionError("naive now must raise ValueError")


# --------------------------------------------------------------------------- #
# import-clean strategy construction (no node)
# --------------------------------------------------------------------------- #


class _DummyPortfolio:
    """Minimal stand-in for the workstream-A Portfolio protocol."""

    def compute_target(self, bars, ts):
        return TargetPosition(ts=ts, target_contracts=0, z_target=0.0, reason="dummy")


class _DummyRisk:
    """Minimal stand-in for the workstream-C RiskController protocol."""

    def gate(self, target):
        return True, ""

    def status(self):
        return RiskState()


def _make_config(**overrides):
    values = {
        "instrument_id": "VN30F1M.HNX",
        "bar_type": "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL",
        "portfolio": _DummyPortfolio(),
        "risk": _DummyRisk(),
    }
    values.update(overrides)
    return BridgeConfig(**values)


def test_bridge_config_defaults():
    config = _make_config()
    assert config.order_style == "LO"
    assert config.cooldown_secs == 5.0
    assert config.min_gap_contracts == 1
    assert config.force_close_local_time == "14:00"
    assert config.warmup_bars == 800
    assert config.buffer_bars == 2000
    assert config.client_order_id_prefix == "bridge"


def test_bridge_strategy_imports_and_constructs_cleanly():
    strategy = BridgeStrategy(_make_config())
    assert isinstance(strategy, Strategy)
    assert strategy.bridge_config.order_style == "LO"
    assert str(strategy._instrument_id) == "VN30F1M.HNX"
    assert strategy._closes.maxlen == 2000


def test_bridge_strategy_rejects_bad_order_style():
    try:
        BridgeStrategy(_make_config(order_style="FOK"))
    except ValueError:
        return
    raise AssertionError("unsupported order_style must raise ValueError")


def test_bridge_strategy_rejects_instrument_bar_type_mismatch():
    try:
        BridgeStrategy(_make_config(instrument_id="OTHER.HNX"))
    except ValueError:
        return
    raise AssertionError("bar_type/instrument_id mismatch must raise ValueError")


def test_bridge_strategy_rejects_buffer_smaller_than_warmup():
    try:
        BridgeStrategy(_make_config(warmup_bars=100, buffer_bars=50))
    except ValueError:
        return
    raise AssertionError("buffer < warmup must raise ValueError")


# --------------------------------------------------------------------------- #
# plain assert runner (pytest is not installed in .venv)
# --------------------------------------------------------------------------- #


def _run_all() -> int:
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:  # noqa: BLE001 - plain runner reports every failure
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    total = len(tests)
    print(f"\n{total - failures}/{total} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
