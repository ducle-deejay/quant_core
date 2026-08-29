"""Unit tests for the Component 7 risk overlay core (workstream C).

Run either with pytest (``.venv/bin/python3 -m pytest``) or as a plain
assert runner (``.venv/bin/python3 src/trading/tests/test_risk.py``);
pytest is not currently installed in ``.venv``, so the ``__main__`` block is
the canonical invocation until it is. The Nautilus actor wrapper
(``trading.risk.overlay``) is not unit-testable without a TradingNode, so the
flatten retry loop is verified by code review against the v1 API reference
(see the module docstring and the integration report).

Governing notes (design-derived tests, ledger rule M4):
- DEC-008  : risk overlay built to live standard in the paper phase; contract
  types from ``trading.contracts``; live/paper process split is an accepted gap
- canon STG-7-RISK-OVERLAY : layer-3 ladder (soft halt / flatten / shutdown),
  layer-2 exposure caps, dead-man's switch / stale-feed detector
- OBS-009 / OBS-010 : entrade margin basis and 100,000 VND contract multiplier
- milestone-1 facts (DEC-008): capital 100,000,000 VND; max 10 contracts

Test-mapping ledger notes (TST-*) are owned by the integrator; none are
written from this workstream.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading.risk.state import (
    ACTIVE,
    HALTED,
    REDUCING,
    REASON_EXCEEDS_MAX,
    REASON_EXPOSURE,
    REASON_LOSS,
    REASON_REDUCING_ONLY,
    REASON_STALE,
    RiskConfig,
    RiskLedger,
    is_session_open,
    parse_close_time,
)

UTC = timezone.utc
HCM = "Asia/Ho_Chi_Minh"
CLOSE = "14:00"

# Session day D: 2026-08-31 (Monday). HCM = UTC+7, so 02:00 UTC = 09:00 local
# (open) and 07:30 UTC = 14:30 local (closed).
DAY_D = datetime(2026, 8, 31, tzinfo=UTC)
OPEN = DAY_D.replace(hour=2, minute=0, second=0)
CLOSED = DAY_D.replace(hour=7, minute=30, second=0)
NEXT_OPEN = OPEN.replace(month=9, day=1)  # 2026-09-01 02:00 UTC

DEFAULT = RiskConfig()  # capital 1e8 VND, max 10 contracts, 2% loss, 60 s stale


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _raises(exc: type[BaseException], fn) -> None:
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__} to be raised")


# --- session helpers ---------------------------------------------------------

def test_session_open_before_close() -> None:
    _assert(is_session_open(OPEN, CLOSE, HCM), "09:00 HCM must be open")
    _assert(
        is_session_open(DAY_D.replace(hour=6, minute=59, second=59), CLOSE, HCM),
        "13:59:59 HCM must be open",
    )


def test_session_closed_at_and_after_close() -> None:
    _assert(
        not is_session_open(DAY_D.replace(hour=7, minute=0), CLOSE, HCM),
        "exactly 14:00 HCM is closed",
    )
    _assert(not is_session_open(CLOSED, CLOSE, HCM), "14:30 HCM must be closed")


def test_session_naive_ts_interpreted_in_tz() -> None:
    naive_open = datetime(2026, 8, 31, 9, 0)  # no tzinfo
    _assert(is_session_open(naive_open, CLOSE, HCM), "naive 09:00 must be read as HCM local")


def test_parse_close_time_rejects_garbage() -> None:
    _raises(ValueError, lambda: parse_close_time("not-a-time"))
    _raises(ValueError, lambda: parse_close_time("25:00"))


# --- intraday loss limit (trigger priority 1) --------------------------------

def test_loss_limit_exact_threshold_halts() -> None:
    """realized+marked == -2% * capital exactly -> HALTED (DEC-008/STG-7)."""
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.record_fill(1500.0, 10, OPEN)  # long 10 @ 1500
    ledger.mark(1498.0, OPEN + timedelta(seconds=1))  # -10 * 2 * 1e5 = -2,000,000
    state = ledger.decide()
    _assert(state.status == HALTED, f"status={state.status}")
    _assert(state.reason == REASON_LOSS, f"reason={state.reason}")


def test_loss_limit_below_threshold_stays_active() -> None:
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.record_fill(1500.0, 10, OPEN)
    ledger.mark(1498.01, OPEN + timedelta(seconds=1))  # -1,990,000 > -2,000,000
    state = ledger.decide()
    _assert(state.status == ACTIVE, f"status={state.status}, reason={state.reason}")


def test_loss_limit_from_realized_fills() -> None:
    """Realized PnL alone (position back to flat) trips the limit."""
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.record_fill(1500.0, 10, OPEN)
    ledger.record_fill(1498.0, -4, OPEN)  # realize -800,000
    ledger.mark(1500.0, OPEN + timedelta(seconds=1))
    _assert(ledger.decide().status == ACTIVE, "partial loss must not trip yet")
    ledger.record_fill(1498.0, -6, OPEN)  # realize another -1,200,000 -> -2,000,000
    _assert(ledger.position == 0 and ledger.avg_entry is None, "must be flat")
    state = ledger.decide()
    _assert(state.status == HALTED and state.reason == REASON_LOSS, "realized loss must halt")


# --- stale-feed dead-man's switch (trigger priority 2) -----------------------

def test_stale_feed_triggers_within_session() -> None:
    ledger = RiskLedger(DEFAULT)  # staleness_secs = 60
    ledger.on_bar(OPEN)
    ledger.mark(1500.0, OPEN + timedelta(seconds=61))
    state = ledger.decide()
    _assert(state.status == HALTED and state.reason == REASON_STALE, "61 s gap must halt")


def test_stale_feed_not_within_window() -> None:
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.mark(1500.0, OPEN + timedelta(seconds=59))
    _assert(ledger.decide().status == ACTIVE, "59 s gap must stay active")
    ledger.mark(1500.0, OPEN + timedelta(seconds=60.0))
    _assert(
        ledger.decide().status == ACTIVE,
        "exactly 60 s gap is not stale (strictly greater)",
    )


def test_stale_feed_ignored_after_session_close() -> None:
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.mark(1500.0, CLOSED)  # 14:30 HCM: session closed
    _assert(ledger.decide().status == ACTIVE, "closed session must not go stale")


def test_stale_feed_last_bar_flags_session() -> None:
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    _assert(ledger.last_bar_seen_session, "in-session bar must set the flag")
    ledger.on_bar(CLOSED)
    _assert(not ledger.last_bar_seen_session, "after-close bar must clear the flag")
    # A fresh in-session bar restores the flag and resets the clock.
    ledger.on_bar(NEXT_OPEN)
    ledger.mark(1500.0, NEXT_OPEN + timedelta(seconds=61))
    state = ledger.decide()
    _assert(
        state.status == HALTED and state.reason == REASON_STALE,
        "new session must re-arm the dead-man's switch",
    )


def test_stale_feed_requires_in_session_last_bar() -> None:
    """Documented edge: a last bar seen after close suppresses staleness at the
    next open (the feed only emits in-session bars, so this is theoretical)."""
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(CLOSED)  # last bar of the day arrived after close
    ledger.mark(1500.0, NEXT_OPEN + timedelta(minutes=5))
    _assert(
        ledger.decide().status == ACTIVE,
        "no in-session last bar -> no staleness verdict (documented edge)",
    )


# --- exposure cap (trigger priority 3) ---------------------------------------

def test_exposure_cap_triggers_reducing() -> None:
    ledger = RiskLedger(DEFAULT)  # max_contracts = 10
    ledger.on_bar(OPEN)
    for _ in range(11):
        ledger.record_fill(1500.0, 1, OPEN)
    state = ledger.decide()
    _assert(state.status == REDUCING and state.reason == REASON_EXPOSURE, "11 > 10 contracts")


def test_exposure_cap_self_heals_when_reduced() -> None:
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    for _ in range(11):
        ledger.record_fill(1500.0, 1, OPEN)
    ledger.decide()
    ledger.record_fill(1500.0, -1, OPEN)  # back to 10
    _assert(ledger.decide().status == ACTIVE, "at-cap position must be ACTIVE")


def test_trigger_priority_loss_over_exposure() -> None:
    """Loss limit wins over the exposure cap when both apply."""
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    for _ in range(11):
        ledger.record_fill(1500.0, 1, OPEN)  # over cap
    ledger.mark(1498.0, OPEN + timedelta(seconds=1))  # and at the loss line
    state = ledger.decide()
    _assert(
        state.status == HALTED and state.reason == REASON_LOSS,
        "loss limit must take priority over exposure-cap",
    )


def test_decide_active_without_events() -> None:
    ledger = RiskLedger(DEFAULT)
    _assert(ledger.decide().status == ACTIVE, "no events -> ACTIVE")


# --- day rollover ------------------------------------------------------------

def test_day_rollover_resets_loss_halt() -> None:
    """The intraday loss limit is per session day: a new local date resets the
    counters and lifts the halt (DEC-008 milestone-1 intraday semantics)."""
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.record_fill(1500.0, 10, OPEN)
    ledger.mark(1498.0, OPEN + timedelta(seconds=1))
    _assert(ledger.decide().status == HALTED, "day D must halt on the loss")

    ledger.on_bar(NEXT_OPEN)  # first bar of day D+1
    _assert(ledger.status == ACTIVE, "rollover must lift the loss halt")
    _assert(ledger.realized_pnl_vnd == 0.0, "intraday realized must reset")
    _assert(ledger.marked_pnl_vnd == 0.0, "intraday marked must reset")
    _assert(ledger.intraday_start_ts == NEXT_OPEN, "intraday_start_ts must advance")
    _assert(ledger.decide().status == ACTIVE, "fresh day must be ACTIVE")


def test_day_rollover_keeps_position() -> None:
    """Positions carry across days; only intraday PnL resets."""
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.record_fill(1500.0, 5, OPEN)
    ledger.mark(1499.0, OPEN + timedelta(seconds=1))  # -500,000 marked
    ledger.on_bar(NEXT_OPEN)
    _assert(ledger.position == 5, "position must survive the rollover")
    _assert(ledger.avg_entry == 1500.0, "avg entry must survive the rollover")
    ledger.mark(1501.0, NEXT_OPEN + timedelta(seconds=1))
    _assert(
        ledger.marked_pnl_vnd == 5 * 1.0 * 100_000.0,
        "fresh-day marking starts from the surviving entry",
    )


# --- realized / marked PnL arithmetic ----------------------------------------

def test_realized_pnl_arithmetic() -> None:
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.record_fill(1500.0, 10, OPEN)
    ledger.record_fill(1502.0, -4, OPEN)  # close 4 @ +2 -> +800,000
    _assert(ledger.position == 6, "position after partial close")
    _assert(ledger.realized_pnl_vnd == 800_000.0, "partial close realization")
    ledger.record_fill(1499.0, -6, OPEN)  # close 6 @ -1 -> -600,000
    _assert(ledger.position == 0 and ledger.avg_entry is None, "must be flat")
    _assert(ledger.realized_pnl_vnd == 200_000.0, "net realized")


def test_realized_pnl_flip() -> None:
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.record_fill(1500.0, 10, OPEN)
    ledger.record_fill(1502.0, -12, OPEN)  # close 10 @ +2, flip 2 short @ 1502
    _assert(ledger.position == -2, "flip leaves a short")
    _assert(ledger.avg_entry == 1502.0, "flip opens at the fill price")
    _assert(ledger.realized_pnl_vnd == 2_000_000.0, "flip realization")


def test_marked_pnl_from_last_close() -> None:
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.record_fill(1500.0, 10, OPEN)
    ledger.mark(1510.0, OPEN + timedelta(seconds=1))
    _assert(ledger.marked_pnl_vnd == 10_000_000.0, "mark up")
    ledger.mark(1490.0, OPEN + timedelta(seconds=2))
    _assert(ledger.marked_pnl_vnd == -10_000_000.0, "mark down")
    ledger.record_fill(1490.0, -10, OPEN)
    ledger.mark(1490.0, OPEN + timedelta(seconds=3))
    _assert(ledger.marked_pnl_vnd == 0.0, "flat position -> zero marked")


# --- gate semantics ----------------------------------------------------------

def _halted_ledger() -> RiskLedger:
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    ledger.record_fill(1500.0, 10, OPEN)
    ledger.mark(1498.0, OPEN + timedelta(seconds=1))
    ledger.decide()
    return ledger


def test_gate_halted_denies_everything() -> None:
    ledger = _halted_ledger()
    allowed, reason = ledger.gate(0, 10)
    _assert(not allowed, "flat target must still be denied while halted")
    _assert(reason == f"halted:{REASON_LOSS}", f"reason={reason}")
    allowed, _ = ledger.gate(5, 10)
    _assert(not allowed, "any target denied while halted")


def _reducing_ledger() -> RiskLedger:
    ledger = RiskLedger(DEFAULT)
    ledger.on_bar(OPEN)
    for _ in range(11):
        ledger.record_fill(1500.0, 1, OPEN)
    ledger.decide()
    return ledger


def test_gate_reducing_allows_only_reducing_moves() -> None:
    ledger = _reducing_ledger()  # position 11, cap 10
    _assert(ledger.gate(10, 11)[0], "11 -> 10 reduces, allowed")
    _assert(ledger.gate(0, 11)[0], "flatten allowed")
    _assert(ledger.gate(-5, 11)[0], "sign flip reduces |position|, allowed")
    allowed, reason = ledger.gate(11, 11)
    _assert(not allowed and reason == REASON_REDUCING_ONLY, "no-op move denied")
    allowed, reason = ledger.gate(12, 11)
    _assert(not allowed and reason == REASON_REDUCING_ONLY, "add-on denied")
    _assert(ledger.gate(9, 11)[0], "reducing move below cap allowed")


def test_gate_active_cap_boundary() -> None:
    ledger = RiskLedger(DEFAULT)  # ACTIVE
    _assert(ledger.gate(10, 0)[0], "target == cap allowed")
    _assert(ledger.gate(-10, 0)[0], "signed cap allowed")
    _assert(ledger.gate(0, 5)[0], "flatten target allowed")
    allowed, reason = ledger.gate(11, 0)
    _assert(not allowed and reason == REASON_EXCEEDS_MAX, "target > cap denied")
    allowed, reason = ledger.gate(-11, 0)
    _assert(not allowed and reason == REASON_EXCEEDS_MAX, "signed target > cap denied")


# --- runner ------------------------------------------------------------------

def _run_all() -> None:
    tests = [
        fn
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"OK: {len(tests)} tests passed")


if __name__ == "__main__":
    _run_all()
