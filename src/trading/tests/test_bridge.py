"""Pure-helper tests for the bridge strategy (workstream B, DEC-008).

Tests are derived from the decision rules in the bridge module and the
``trading.contracts`` protocols; governing notes: DEC-008 (live wiring
architecture), STG-6-TRADE-SCHEDULING design intent. No node execution, no
credentials: only pure helpers, the JSONL decision-log writers, and
import-time construction are exercised.

Runs under pytest when available, and also as a plain assert runner:

    .venv/bin/python3 src/trading/tests/test_bridge.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
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
from trading.strategies.bridge import append_decision
from trading.strategies.bridge import bar_period_timedelta
from trading.strategies.bridge import client_order_id_for
from trading.strategies.bridge import format_decision
from trading.strategies.bridge import has_working_orders
from trading.strategies.bridge import in_session_window
from trading.strategies.bridge import is_below_min_gap
from trading.strategies.bridge import is_cooldown_elapsed
from trading.strategies.bridge import is_expiry_day_entry_blocked
from trading.strategies.bridge import is_force_close_day
from trading.strategies.bridge import order_side_for_delta
from trading.strategies.bridge import should_force_close
from trading.strategies.bridge import target_delta
from trading.strategies.bridge import warmup_start

UTC = timezone.utc
VN = ZoneInfo("Asia/Ho_Chi_Minh")

#: Default VN session windows (morning + afternoon; lunch/ATO/ATC excluded).
DEFAULT_WINDOWS = [("09:00", "11:30"), ("13:00", "14:30")]


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
# expiry-day force-close (is_force_close_day)
# --------------------------------------------------------------------------- #


def test_is_force_close_day_in_list():
    assert is_force_close_day(_vn(2026, 9, 18, 14, 0), ["2026-09-18"], VN_TZ)


def test_is_force_close_day_not_in_list():
    assert not is_force_close_day(_vn(2026, 9, 17, 14, 0), ["2026-09-18"], VN_TZ)


def test_is_force_close_day_empty_list_never_fires():
    assert not is_force_close_day(_vn(2026, 9, 18, 14, 0), [], VN_TZ)


def test_is_force_close_day_multiple_dates():
    dates = ["2026-09-17", "2026-09-18"]
    assert is_force_close_day(_vn(2026, 9, 17, 9, 30), dates, VN_TZ)
    assert is_force_close_day(_vn(2026, 9, 18, 14, 0), dates, VN_TZ)
    assert not is_force_close_day(_vn(2026, 9, 19, 14, 0), dates, VN_TZ)


def test_is_force_close_day_utc_crosses_date_boundary():
    # UTC 2026-09-17 17:30 == VN 2026-09-18 00:30 -> the VN date decides.
    utc_ts = datetime(2026, 9, 17, 17, 30, tzinfo=UTC)
    assert is_force_close_day(utc_ts, ["2026-09-18"], VN_TZ)
    assert not is_force_close_day(utc_ts, ["2026-09-17"], VN_TZ)
    # UTC 2026-09-17 16:59 == VN 23:59 on the 17th.
    assert not is_force_close_day(datetime(2026, 9, 17, 16, 59, tzinfo=UTC), ["2026-09-18"], VN_TZ)


def test_is_force_close_day_rejects_naive_timestamp():
    try:
        is_force_close_day(datetime(2026, 9, 18, 14, 0), ["2026-09-18"], VN_TZ)
    except ValueError:
        return
    raise AssertionError("naive timestamp must raise ValueError")


# --------------------------------------------------------------------------- #
# session windows (in_session_window)
# --------------------------------------------------------------------------- #


def test_in_session_window_inside_morning():
    assert in_session_window(_vn(2026, 9, 18, 9, 0, 1), DEFAULT_WINDOWS, VN_TZ)
    assert in_session_window(_vn(2026, 9, 18, 10, 30, 0), DEFAULT_WINDOWS, VN_TZ)
    assert in_session_window(_vn(2026, 9, 18, 11, 29, 59), DEFAULT_WINDOWS, VN_TZ)


def test_in_session_window_inside_afternoon():
    assert in_session_window(_vn(2026, 9, 18, 13, 0, 0), DEFAULT_WINDOWS, VN_TZ)
    assert in_session_window(_vn(2026, 9, 18, 14, 0, 0), DEFAULT_WINDOWS, VN_TZ)
    assert in_session_window(_vn(2026, 9, 18, 14, 29, 59), DEFAULT_WINDOWS, VN_TZ)


def test_in_session_window_lunch_gap():
    assert not in_session_window(_vn(2026, 9, 18, 11, 30, 0), DEFAULT_WINDOWS, VN_TZ)
    assert not in_session_window(_vn(2026, 9, 18, 12, 0, 0), DEFAULT_WINDOWS, VN_TZ)
    assert not in_session_window(_vn(2026, 9, 18, 12, 59, 59), DEFAULT_WINDOWS, VN_TZ)


def test_in_session_window_before_open():
    assert not in_session_window(_vn(2026, 9, 18, 0, 0, 0), DEFAULT_WINDOWS, VN_TZ)
    assert not in_session_window(_vn(2026, 9, 18, 8, 59, 59), DEFAULT_WINDOWS, VN_TZ)


def test_in_session_window_after_close():
    assert not in_session_window(_vn(2026, 9, 18, 14, 30, 0), DEFAULT_WINDOWS, VN_TZ)
    assert not in_session_window(_vn(2026, 9, 18, 23, 59, 59), DEFAULT_WINDOWS, VN_TZ)


def test_in_session_window_utc_input_converted_to_vn():
    # 03:00 UTC == 10:00 VN -> inside morning.
    assert in_session_window(datetime(2026, 9, 18, 3, 0, 0, tzinfo=UTC), DEFAULT_WINDOWS, VN_TZ)
    # 04:30 UTC == 11:30 VN -> lunch boundary, outside.
    assert not in_session_window(datetime(2026, 9, 18, 4, 30, 0, tzinfo=UTC), DEFAULT_WINDOWS, VN_TZ)


def test_in_session_window_rejects_naive_timestamp():
    try:
        in_session_window(datetime(2026, 9, 18, 10, 0), DEFAULT_WINDOWS, VN_TZ)
    except ValueError:
        return
    raise AssertionError("naive timestamp must raise ValueError")


# --------------------------------------------------------------------------- #
# delta / gap / cooldown / stacking decisions
# --------------------------------------------------------------------------- #


def test_target_delta_values():
    assert target_delta(3, 1) == 2
    assert target_delta(-2, 1) == -3
    assert target_delta(0, 0) == 0
    assert target_delta(0, 4) == -4


def test_expiry_day_entry_flat_position_blocked():
    # Flat -> any non-zero delta is an entry, blocked on the expiry day.
    assert is_expiry_day_entry_blocked(0, 2)
    assert is_expiry_day_entry_blocked(0, -3)


def test_expiry_day_entry_reduce_allowed():
    assert not is_expiry_day_entry_blocked(3, -2)  # 3 -> 1
    assert not is_expiry_day_entry_blocked(-3, 2)  # -3 -> -1
    assert not is_expiry_day_entry_blocked(3, -3)  # 3 -> 0 (flat)


def test_expiry_day_entry_increase_blocked():
    assert is_expiry_day_entry_blocked(3, 2)  # 3 -> 5
    assert is_expiry_day_entry_blocked(-3, -2)  # -3 -> -5


def test_expiry_day_entry_flip_through_zero():
    # +5 -> -3 via delta -8: |position| 5 -> 3, reduces -> allowed.
    assert not is_expiry_day_entry_blocked(5, -8)
    # +2 -> -3 via delta -5: |position| 2 -> 3, increases -> blocked.
    assert is_expiry_day_entry_blocked(2, -5)


def test_expiry_day_entry_noop_delta_zero_blocked():
    # No change means no reduction: nothing may be submitted on an expiry day.
    assert is_expiry_day_entry_blocked(4, 0)
    assert is_expiry_day_entry_blocked(0, 0)


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
    # 800 bars x 1 min x calendar multiple 10.0 (VN trading-hours inflation).
    assert start == now - timedelta(minutes=8000)
    assert start.tzinfo is not None


def test_warmup_start_rejects_naive_now():
    try:
        warmup_start(datetime(2026, 9, 1, 3, 0, 0), "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL", 800)
    except ValueError:
        return
    raise AssertionError("naive now must raise ValueError")


# --------------------------------------------------------------------------- #
# per-bar decision log (format_decision / append_decision)
# --------------------------------------------------------------------------- #


def test_format_decision_schema():
    line = format_decision(
        ts_event_ns=1_700_000_000_000_000_000,
        clock_ns=1_700_000_000_000_060_000,
        close=1500.5,
        target=3,
        current_contracts=1,
        action="submit",
        reason=None,
    )
    assert json.loads(line) == {
        "ts_event_ns": 1_700_000_000_000_000_000,
        "clock_ns": 1_700_000_000_000_060_000,
        "close": 1500.5,
        "target": 3,
        "current_contracts": 1,
        "action": "submit",
        "reason": None,
    }


def test_format_decision_nulls_when_not_computed():
    # skip-warmup fires before compute_target: close/target/reason are null.
    line = format_decision(123, 456, None, None, 0, "skip-warmup", None)
    record = json.loads(line)
    assert record["close"] is None
    assert record["target"] is None
    assert record["reason"] is None
    assert record["current_contracts"] == 0
    assert record["action"] == "skip-warmup"


def test_format_decision_carries_risk_reason():
    line = format_decision(1, 2, 1500.0, 5, 2, "skip-denied", "max_contracts breached")
    assert json.loads(line)["reason"] == "max_contracts breached"


def test_append_decision_writes_valid_json_lines():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "decisions.jsonl")
        assert append_decision(path, {"action": "submit", "target": 3})
        assert append_decision(path, {"action": "skip-gap", "reason": None})
        with open(path, encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        assert records == [
            {"action": "submit", "target": 3},
            {"action": "skip-gap", "reason": None},
        ]


def test_append_decision_accepts_preformatted_line():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "decisions.jsonl")
        line = format_decision(1, 2, None, None, 0, "skip-warmup", None)
        assert append_decision(path, line)
        with open(path, encoding="utf-8") as handle:
            assert json.loads(handle.readline())["action"] == "skip-warmup"


def test_append_decision_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "nested", "deep", "decisions.jsonl")
        assert append_decision(path, {"action": "force-close"})
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as handle:
            assert json.loads(handle.readline())["action"] == "force-close"


def test_append_decision_never_raises_on_unwritable_path():
    with tempfile.TemporaryDirectory() as tmp:
        blocker = os.path.join(tmp, "blocker")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")
        # Parent is a regular file, so makedirs fails -> returns False, no raise.
        bad_path = os.path.join(blocker, "decisions.jsonl")
        assert not append_decision(bad_path, {"action": "submit"})


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
    assert config.force_close_dates == []  # empty = never force-close
    assert config.session_windows == DEFAULT_WINDOWS
    assert config.decision_log_path is None  # no logging by default
    assert config.warmup_bars == 7200
    assert config.buffer_bars == 8000
    assert config.client_order_id_prefix == "bridge"


def test_bridge_strategy_imports_and_constructs_cleanly():
    strategy = BridgeStrategy(_make_config())
    assert isinstance(strategy, Strategy)
    assert strategy.bridge_config.order_style == "LO"
    assert str(strategy._instrument_id) == "VN30F1M.HNX"
    assert strategy._closes.maxlen == 8000


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


def test_bridge_strategy_rejects_empty_session_windows():
    try:
        BridgeStrategy(_make_config(session_windows=[]))
    except ValueError:
        return
    raise AssertionError("empty session_windows must raise ValueError")


def test_bridge_strategy_rejects_bad_session_window_time():
    for windows in ([("25:00", "11:30")], [("09:00", "11:60")], [("09:00",)]):
        try:
            BridgeStrategy(_make_config(session_windows=windows))
        except ValueError:
            continue
        raise AssertionError(f"bad session window {windows!r} must raise ValueError")


def test_bridge_strategy_accepts_session_windows_override():
    strategy = BridgeStrategy(_make_config(session_windows=[("09:15", "11:30")]))
    assert strategy.bridge_config.session_windows == [("09:15", "11:30")]


def test_bridge_strategy_rejects_malformed_force_close_date():
    for bad in ("2026/09/18", "2026-9-8", "2026-09-18T00:00:00", "not-a-date"):
        try:
            BridgeStrategy(_make_config(force_close_dates=[bad]))
        except ValueError:
            continue
        raise AssertionError(f"malformed force_close_date {bad!r} must raise ValueError")


def test_bridge_strategy_accepts_iso_force_close_dates():
    strategy = BridgeStrategy(_make_config(force_close_dates=["2026-09-18", "2026-12-17"]))
    assert strategy.bridge_config.force_close_dates == ["2026-09-18", "2026-12-17"]


def test_bridge_strategy_wires_decision_log_path():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "log.jsonl")
        strategy = BridgeStrategy(_make_config(decision_log_path=path))
        assert strategy.bridge_config.decision_log_path == path


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
