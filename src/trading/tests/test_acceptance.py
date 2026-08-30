"""Acceptance-report tests: six post-session checks in ``apps.trading.acceptance``.

The checks are pure functions over plain records (no Nautilus runtime), so
most tests craft in-memory bars/orders/positions/decisions; catalog adapters
are exercised against a tmp ``ParquetDataCatalog`` (parquet round-trip) and a
handcrafted feather instance directory (the ``read_live_run`` streaming path).

Governing notes (design-derived tests, ledger rule M4): DEC-006 (scalar
per-side fee model), DEC-008 (live wiring: decision log, transition log,
streaming subset), STG-6-TRADE-SCHEDULING (one target/one working order),
STG-7-RISK-OVERLAY (trigger matrix + flatten circuit breaker).

Runs as a plain assert runner:

    .venv/bin/python3 src/trading/tests/test_acceptance.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from datetime import datetime
from datetime import timezone
from pathlib import Path

import pyarrow as pa

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import register_currency
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarSpecification
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AggregationSource
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.model.enums import LiquiditySide
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import OrderType
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.events.order import OrderFilled
from nautilus_trader.model.events.order import OrderSubmitted
from nautilus_trader.model.events.position import PositionOpened
from nautilus_trader.model.identifiers import AccountId
from nautilus_trader.model.identifiers import ClientOrderId
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import PositionId
from nautilus_trader.model.identifiers import StrategyId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.identifiers import TradeId
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.identifiers import VenueOrderId
from nautilus_trader.model.objects import Currency
from nautilus_trader.model.objects import Money
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.writer import class_to_filename
from nautilus_trader.persistence.writer import urisafe_identifier
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

_THIS_DIR = Path(__file__).resolve().parent
_SRC = _THIS_DIR.parents[2]
_REPO_ROOT = _THIS_DIR.parents[3]
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_REPO_ROOT))

from trading.contracts import TargetPosition  # noqa: E402

from apps.trading.acceptance import (  # noqa: E402
    KIND_CANCELED,
    KIND_DENIED,
    KIND_EXPIRED,
    KIND_FILLED,
    KIND_REJECTED,
    KIND_SUBMITTED,
    AcceptanceParams,
    BarRecord,
    Decision,
    OrderRecord,
    PositionRecord,
    Transition,
    build_portfolio,
    check_cost,
    check_data_parity,
    check_execution,
    check_position,
    check_risk,
    check_signal_parity,
    compute_checks,
    load_decisions,
    load_transitions,
    nautilus_order_records,
    nautilus_position_records,
    partition_streamed,
    read_research_bars,
    read_streamed_objects,
    rebuild_snapshots,
    resolve_params,
)

UTC = timezone.utc

BAR_TYPE = "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL"
INSTRUMENT = "VN30F1M.HNX"
PERIOD_NS = 60_000_000_000

# VND must be registered before any Money/commission object is built.
register_currency(Currency("VND", 0, 704, "Vietnamese dong", 1), overwrite=True)
VND = Currency("VND", 0, 704, "Vietnamese dong", 1)

#: 2026-09-03 02:00 UTC == 09:00 VN (the paper session day).
_BASE = int(datetime(2026, 9, 3, 2, 0, tzinfo=UTC).timestamp() * 1e9)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _bar(ts: int, close: float, volume: float = 100.0) -> BarRecord:
    return BarRecord(ts_event_ns=ts, close=close, volume=volume)


def _decision(
    ts: int,
    clock: int,
    action: str,
    target: int | None = None,
    close: float | None = None,
    current: int = 0,
) -> Decision:
    return Decision(
        ts_event_ns=ts,
        clock_ns=clock,
        close=close,
        target=target,
        current_contracts=current,
        action=action,
        reason=None,
    )


class _StubPortfolio:
    """Deterministic stand-in: target = round(last close - 1500)."""

    def compute_target(self, bars, ts):
        target = int(round(bars["close"][-1] - 1500.0))
        return TargetPosition(ts=ts, target_contracts=target, z_target=0.0, reason="stub")


def _fill(coid: str, side: str, qty: int, price: float, ts: int, commission: float = 0.0) -> OrderRecord:
    return OrderRecord(
        coid=coid,
        kind=KIND_FILLED,
        ts_event_ns=ts,
        side=side,
        qty=float(qty),
        price=price,
        commission=commission,
    )


# --------------------------------------------------------------------------- #
# JSONL loaders
# --------------------------------------------------------------------------- #


def test_loaders_round_trip_jsonl() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        decisions_path = Path(tmp) / "decisions.jsonl"
        decisions_path.write_text(
            "\n".join(
                [
                    '{"ts_event_ns": 100, "clock_ns": 110, "close": 1500.5, "target": 3, '
                    '"current_contracts": 1, "action": "submit", "reason": null}',
                    '{"ts_event_ns": 60, "clock_ns": 70, "close": null, "target": null, '
                    '"current_contracts": 0, "action": "skip-warmup", "reason": null}',
                ],
            )
            + "\n",
            encoding="utf-8",
        )
        decisions = load_decisions(decisions_path)
        _assert(len(decisions) == 2, f"decisions={len(decisions)}")
        _assert(decisions[0].ts_event_ns == 60, "sorted by ts_event")
        _assert(decisions[1].action == "submit" and decisions[1].target == 3, decisions[1])

        transitions_path = Path(tmp) / "risk_transitions.jsonl"
        transitions_path.write_text(
            '{"ts_ns": 5, "previous": "<start>", "current": "ACTIVE", "reason": "startup"}\n'
            '{"ts_ns": 9, "previous": "ACTIVE", "current": "ACTIVE", "reason": null}\n',
            encoding="utf-8",
        )
        transitions = load_transitions(transitions_path)
        _assert(len(transitions) == 2, f"transitions={len(transitions)}")
        _assert(transitions[1].reason == "", "None reason normalised to empty string")


# --------------------------------------------------------------------------- #
# Check 1 - data parity
# --------------------------------------------------------------------------- #


def test_data_parity_identical_windows_pass() -> None:
    research = [_bar(1, 1500.0), _bar(2, 1500.1)]
    result = check_data_parity(
        research,
        list(research),
        research,
        list(research),
        live_catalog_pending=False,
    )
    _assert(result.status == "PASS", result.status)
    for window in ("warmup", "live"):
        numbers = result.numbers[window]
        _assert(
            numbers["gaps"] == 0 and numbers["dups"] == 0 and numbers["price_mismatches"] == 0,
            numbers,
        )


def test_data_parity_detects_gaps_dups_and_price_mismatch() -> None:
    research_warmup = [_bar(1, 1500.0), _bar(2, 1500.1), _bar(3, 1500.5)]
    # Streamed: ts 2 missing (gap), ts 1 duplicated, ts 3 close off by 0.3 (> 0.1).
    streamed_warmup = [_bar(1, 1500.0), _bar(1, 1500.0), _bar(3, 1500.8)]
    result = check_data_parity(
        research_warmup,
        streamed_warmup,
        research_warmup,
        list(research_warmup),
        live_catalog_pending=False,
    )
    _assert(result.status == "FAIL", result.status)
    numbers = result.numbers["warmup"]
    _assert(numbers["gaps"] == 1 and numbers["dups"] == 1 and numbers["price_mismatches"] == 1, numbers)
    _assert(numbers["first_gap_ts_ns"] == 2, "first gap identified")
    _assert(result.detail is not None and "warmup" in result.detail, result.detail)


def test_data_parity_live_pending_warns_not_fails() -> None:
    research = [_bar(1, 1500.0)]
    result = check_data_parity(
        research,
        list(research),
        research_live=[],
        streamed_live=[_bar(10, 1500.0)],
        live_catalog_pending=True,
    )
    _assert(result.status == "WARN", result.status)
    _assert(result.numbers["live"]["catalog_pending"] is True, "pending flag")
    _assert("16:00" in (result.detail or ""), result.detail)


# --------------------------------------------------------------------------- #
# Check 2 - signal parity
# --------------------------------------------------------------------------- #


def test_signal_parity_equal_recompute_pass() -> None:
    warmup = [_bar(1, 1500.0), _bar(2, 1500.0), _bar(3, 1500.0)]
    live = [_bar(4, 1502.0), _bar(5, 1503.0)]  # stub targets: 2, 3
    decisions = [
        _decision(1, 11, "skip-warmup"),
        _decision(2, 21, "skip-warmup"),
        _decision(3, 31, "skip-warmup"),
        _decision(4, 41, "submit", target=2, close=1502.0),
        _decision(5, 51, "submit", target=3, close=1503.0),
    ]
    result = check_signal_parity(decisions, warmup, live, _StubPortfolio(), buffer_bars=10)
    _assert(result.status == "PASS", result.status)
    _assert(result.numbers["recomputed"] == 2, result.numbers)
    _assert(result.numbers["diffs"] == 0, result.numbers)


def test_signal_parity_diff_recompute_fails_with_detail() -> None:
    warmup = [_bar(1, 1500.0)]
    live = [_bar(2, 1502.0)]  # stub target 2
    decisions = [
        _decision(1, 11, "skip-warmup"),
        _decision(2, 21, "submit", target=5, close=1502.0),  # logged 5 != recomputed 2
    ]
    result = check_signal_parity(decisions, warmup, live, _StubPortfolio(), buffer_bars=10)
    _assert(result.status == "FAIL", result.status)
    _assert(result.numbers["diffs"] == 1, result.numbers)
    first = result.numbers["first_diff"]
    _assert(first["logged_target"] == 5 and first["recomputed_target"] == 2, first)
    _assert(result.detail is not None and "logged target 5" in result.detail, result.detail)


def test_signal_parity_rebuild_dedups_and_caps_buffer() -> None:
    warmup = [_bar(1, 1500.0), _bar(2, 1500.0), _bar(3, 1500.0)]
    live = [_bar(3, 1500.9), _bar(4, 1502.0), _bar(5, 1503.0)]  # ts 3 overlaps warmup
    snapshots = rebuild_snapshots(warmup, live, buffer_bars=3)
    _assert(len(snapshots) == 5, f"dedup -> 5 distinct bars, got {len(snapshots)}")
    # The dedup keeps the first occurrence (warmup ts 3), mirroring
    # bridge._append_bar; the buffer caps at 3, evicting the oldest bars.
    _assert(
        snapshots[5]["close"] == [1500.0, 1502.0, 1503.0],
        snapshots[5]["close"],
    )
    _assert(snapshots[4]["close"] == [1500.0, 1500.0, 1502.0], snapshots[4]["close"])


# --------------------------------------------------------------------------- #
# Check 3 - execution
# --------------------------------------------------------------------------- #


def test_execution_mapping_cooldown_slippage_pass() -> None:
    clock1, clock2 = 1_000_000_000, 61_000_000_000  # 60 s apart
    decisions = [
        _decision(100, clock1, "submit", target=2, close=1500.0),
        _decision(160, clock2, "submit", target=3, close=1501.0),
    ]
    orders = [
        OrderRecord(coid=f"bridge-{clock1}", kind=KIND_SUBMITTED, ts_event_ns=clock1),
        OrderRecord(coid=f"bridge-{clock2}", kind=KIND_SUBMITTED, ts_event_ns=clock2),
        _fill(f"bridge-{clock1}", "BUY", 2, 1500.4, clock1 + 1_000, commission=45.8),
        _fill(f"bridge-{clock2}", "BUY", 1, 1501.2, clock2 + 1_000, commission=34.4),
    ]
    result = check_execution(decisions, orders, cooldown_secs=5.0, client_order_id_prefix="bridge")
    _assert(result.status == "PASS", f"{result.status}: {result.detail}")
    _assert(result.numbers["matched"] == 2, result.numbers)
    _assert(result.numbers["cooldown_violations"] == 0, result.numbers)
    _assert(result.numbers["slippage_count"] == 2, result.numbers)
    _assert(
        abs(result.numbers["slippage_mean"] - (0.4 + 0.2) / 2) < 1e-9,
        result.numbers["slippage_mean"],
    )
    _assert(result.numbers["terminal"][KIND_FILLED] == 2, result.numbers["terminal"])
    _assert(result.numbers["outcome_difference"] == 0, result.numbers)


def test_execution_fails_on_missing_submit_and_cooldown_violation() -> None:
    clock1, clock2, clock3 = 1_000_000_000, 2_000_000_000, 3_000_000_000  # 1 s apart < 5 s cooldown
    decisions = [
        _decision(100, clock1, "submit", target=2, close=1500.0),
        _decision(160, clock2, "submit", target=3, close=1501.0),
        _decision(220, clock3, "submit", target=1, close=1502.0),
    ]
    # Only two OrderSubmitted events: clock3's is missing.
    orders = [
        OrderRecord(coid=f"bridge-{clock1}", kind=KIND_SUBMITTED, ts_event_ns=clock1),
        OrderRecord(coid=f"bridge-{clock2}", kind=KIND_SUBMITTED, ts_event_ns=clock2),
        _fill(f"bridge-{clock1}", "BUY", 2, 1500.0, clock1 + 1_000),
        _fill(f"bridge-{clock2}", "BUY", 1, 1501.0, clock2 + 1_000),
    ]
    result = check_execution(decisions, orders, cooldown_secs=5.0, client_order_id_prefix="bridge")
    _assert(result.status == "FAIL", result.status)
    _assert(len(result.numbers["missing_coids"]) == 1, result.numbers["missing_coids"])
    _assert(result.numbers["cooldown_violations"] == 2, result.numbers["cooldown_violations"])
    # The missing OrderSubmitted is caught by the mapping check (a); the two
    # events that did arrive both filled, so outcome accounting balances.
    _assert(result.numbers["outcome_difference"] == 0, result.numbers["outcome_difference"])


def test_execution_outcome_accounting_partial_fill_then_cancel() -> None:
    clock = 5_000_000
    decisions = [_decision(100, clock, "submit", target=4, close=1500.0)]
    orders = [
        OrderRecord(coid=f"bridge-{clock}", kind=KIND_SUBMITTED, ts_event_ns=clock),
        _fill(f"bridge-{clock}", "BUY", 1, 1500.0, clock + 1_000),  # partial: 1 of 4
        OrderRecord(coid=f"bridge-{clock}", kind=KIND_CANCELED, ts_event_ns=clock + 2_000),
    ]
    result = check_execution(decisions, orders, cooldown_secs=5.0, client_order_id_prefix="bridge")
    _assert(result.status == "PASS", f"{result.status}: {result.detail}")
    _assert(result.numbers["terminal"][KIND_CANCELED] == 1, result.numbers["terminal"])
    _assert(result.numbers["outcome_difference"] == 0, "partial fill + cancel is accounted")


# --------------------------------------------------------------------------- #
# Check 4 - position
# --------------------------------------------------------------------------- #


def test_position_target_following_pass() -> None:
    ts1, ts2 = _BASE, _BASE + PERIOD_NS
    decisions = [
        _decision(ts1, ts1 + 100, "submit", target=2, close=1500.0),
        _decision(ts2, ts2 + 100, "submit", target=5, close=1501.0),
    ]
    # Fills land within their bar: position reaches each target before the next submit.
    position_series = [
        PositionRecord(ts_event_ns=ts1 + 1_000, signed_qty=2),
        PositionRecord(ts_event_ns=ts2 + 1_000, signed_qty=5),
    ]
    orders = [
        OrderRecord(coid="bridge-1", kind=KIND_SUBMITTED, ts_event_ns=ts1 + 100),
        OrderRecord(coid="bridge-1", kind=KIND_FILLED, ts_event_ns=ts1 + 1_000, side="BUY", qty=2.0),
        OrderRecord(coid="bridge-2", kind=KIND_SUBMITTED, ts_event_ns=ts2 + 100),
        OrderRecord(coid="bridge-2", kind=KIND_FILLED, ts_event_ns=ts2 + 1_000, side="BUY", qty=3.0),
    ]
    result = check_position(decisions, position_series, orders, bar_period_ns=PERIOD_NS)
    _assert(result.status == "PASS", f"{result.status}: {result.detail}")
    _assert(result.numbers["max_deviation_contracts"] == 0, result.numbers)
    _assert(result.numbers["deviation_bars_over_1"] == 0, result.numbers)
    _assert(result.numbers["targets_unreached"] == 0, result.numbers)
    _assert(result.numbers["working_orders_at_end"] == 0, result.numbers)


def test_position_unreached_target_fails() -> None:
    ts1 = _BASE
    decisions = [_decision(ts1, ts1 + 100, "submit", target=5, close=1500.0)]
    position_series = []  # no fill ever lands: position stays 0
    orders = [OrderRecord(coid="bridge-1", kind=KIND_SUBMITTED, ts_event_ns=ts1 + 100)]
    result = check_position(decisions, position_series, orders, bar_period_ns=PERIOD_NS)
    _assert(result.status == "FAIL", result.status)
    _assert(result.numbers["max_deviation_contracts"] == 5, result.numbers)
    _assert(result.numbers["targets_unreached"] == 1, result.numbers)
    _assert("deviates" in (result.detail or ""), result.detail)


def test_position_force_close_flat_and_working_order_at_end() -> None:
    ts1, ts2 = _BASE, _BASE + PERIOD_NS
    decisions = [
        _decision(ts1, ts1 + 100, "submit", target=3, close=1500.0),
        _decision(ts2, ts2 + 100, "force-close"),
    ]
    position_series = [
        PositionRecord(ts_event_ns=ts1 + 1_000, signed_qty=3),
        PositionRecord(ts_event_ns=ts2 + 1_000, signed_qty=0),  # flatten fills
    ]
    # One order never reached a terminal state: the flatten submit is working.
    orders = [
        OrderRecord(coid="bridge-1", kind=KIND_SUBMITTED, ts_event_ns=ts1 + 100),
        OrderRecord(coid="bridge-1", kind=KIND_FILLED, ts_event_ns=ts1 + 1_000, side="BUY", qty=3.0),
        OrderRecord(coid="risk-flatten-1", kind=KIND_SUBMITTED, ts_event_ns=ts2 + 100),
    ]
    result = check_position(decisions, position_series, orders, bar_period_ns=PERIOD_NS)
    _assert(result.status == "FAIL", result.status)
    _assert(result.numbers["force_close_action"] is True, result.numbers)
    _assert(result.numbers["final_position"] == 0, "flatten fills -> flat at end")
    _assert(result.numbers["working_orders_at_end"] == 1, result.numbers)
    _assert("working order" in (result.detail or ""), result.detail)


# --------------------------------------------------------------------------- #
# Check 5 - cost (report-only)
# --------------------------------------------------------------------------- #


def test_cost_arithmetic_matches_model_fee() -> None:
    cost_per_side = 0.000229
    multiplier = 100_000.0
    fills = [
        _fill("c1", "BUY", 2, 1500.0, 1_000, commission=0.000229 * 1500.0 * 2 * multiplier),
        _fill("c2", "SELL", 1, 1510.0, 2_000, commission=0.000229 * 1510.0 * 1 * multiplier + 500.0),
    ]
    result = check_cost(fills, cost_per_side=cost_per_side, contract_multiplier=multiplier)
    _assert(result.status == "REPORT" and result.gated is False, (result.status, result.gated))
    numbers = result.numbers
    _assert(numbers["fills"] == 2, numbers)
    _assert(
        abs(numbers["total_model_vnd"] - (0.000229 * 1500.0 * 2 * 100000 + 0.000229 * 1510.0 * 1 * 100000)) < 1e-6,
        numbers["total_model_vnd"],
    )
    _assert(abs(numbers["diff_vnd"] - 500.0) < 1e-6, numbers["diff_vnd"])
    _assert(len(numbers["per_fill"]) == 2, "per-fill breakdown present")


# --------------------------------------------------------------------------- #
# Check 6 - risk
# --------------------------------------------------------------------------- #


def test_risk_matrix_valid_pass_no_flatten_needed() -> None:
    transitions = [
        Transition(ts_ns=1, previous="<start>", current="ACTIVE", reason="startup"),
        Transition(ts_ns=2, previous="ACTIVE", current="REDUCING", reason="exposure-cap"),
        Transition(ts_ns=3, previous="REDUCING", current="ACTIVE", reason=""),
        Transition(ts_ns=4, previous="ACTIVE", current="HALTED", reason="stale-feed"),
        Transition(ts_ns=5, previous="HALTED", current="ACTIVE", reason=""),
    ]
    result = check_risk(transitions, position_series=[], orders=[], flatten_window_secs=60.0)
    _assert(result.status == "PASS", f"{result.status}: {result.detail}")
    _assert(result.numbers["invalid_transitions"] == 0, result.numbers)
    # The HALTED transition is vacuous here: position at halt was 0.
    _assert(result.numbers["flatten_ok"] == 1, result.numbers)


def test_risk_matrix_invalid_state_and_reason_fails() -> None:
    transitions = [
        Transition(ts_ns=1, previous="<start>", current="ACTIVE", reason="startup"),
        Transition(ts_ns=2, previous="ACTIVE", current="HALTED", reason="exposure-cap"),
        Transition(ts_ns=3, previous="HALTED", current="BOGUS", reason=""),
    ]
    result = check_risk(transitions, position_series=[], orders=[], flatten_window_secs=60.0)
    _assert(result.status == "FAIL", result.status)
    _assert(result.numbers["invalid_transitions"] == 2, result.numbers["invalid"])
    _assert("exposure-cap" in (result.detail or ""), result.detail)


def test_risk_flatten_timing_pass_within_window() -> None:
    halt_ts = 10_000_000_000
    transitions = [Transition(ts_ns=halt_ts, previous="ACTIVE", current="HALTED", reason="stale-feed")]
    position_series = [PositionRecord(ts_event_ns=halt_ts - 1, signed_qty=5)]
    orders = [
        OrderRecord(coid="risk-flat", kind=KIND_SUBMITTED, ts_event_ns=halt_ts + 1_000_000_000, side="SELL"),
        _fill("risk-flat", "SELL", 5, 1499.0, halt_ts + 5_000_000_000),
    ]
    result = check_risk(transitions, position_series, orders, flatten_window_secs=60.0)
    _assert(result.status == "PASS", f"{result.status}: {result.detail}")
    _assert(result.numbers["flatten_ok"] == 1, result.numbers)
    _assert(abs(result.numbers["flatten_times_secs"][0] - 5.0) < 1e-9, result.numbers["flatten_times_secs"])


def test_risk_flatten_timing_fails_outside_window() -> None:
    halt_ts = 10_000_000_000
    transitions = [Transition(ts_ns=halt_ts, previous="ACTIVE", current="HALTED", reason="intraday-loss-limit")]
    position_series = [PositionRecord(ts_event_ns=halt_ts - 1, signed_qty=3)]
    orders = [
        _fill("risk-flat", "SELL", 3, 1499.0, halt_ts + 90_000_000_000),  # 90 s > 60 s window
    ]
    result = check_risk(transitions, position_series, orders, flatten_window_secs=60.0)
    _assert(result.status == "FAIL", result.status)
    _assert(result.numbers["flatten_fail"] == 1, result.numbers)
    _assert("flatten did not complete" in (result.detail or ""), result.detail)


# --------------------------------------------------------------------------- #
# Catalog adapters
# --------------------------------------------------------------------------- #


def _nautilus_bar(ts: int, close: float, volume: int = 100) -> Bar:
    bar_type = BarType(
        InstrumentId(Symbol("VN30F1M"), Venue("HNX")),
        BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST),
        AggregationSource.EXTERNAL,
    )
    return Bar(
        bar_type,
        Price(close, 1),
        Price(close + 1.0, 1),
        Price(close - 1.0, 1),
        Price(close, 1),
        Quantity(volume, 0),
        ts,
        ts,
    )


def _nautilus_submitted(coid: str, ts: int) -> OrderSubmitted:
    return OrderSubmitted(
        trader_id=TraderId("TRADER-001"),
        strategy_id=StrategyId("BridgeStrategy-bridge"),
        instrument_id=InstrumentId(Symbol("VN30F1M"), Venue("HNX")),
        client_order_id=ClientOrderId(coid),
        account_id=AccountId("ENTRADE-DEMO"),
        event_id=UUID4(),
        ts_event=ts,
        ts_init=ts,
    )


def _nautilus_filled(coid: str, ts: int, commission: float) -> OrderFilled:
    return OrderFilled(
        trader_id=TraderId("TRADER-001"),
        strategy_id=StrategyId("BridgeStrategy-bridge"),
        instrument_id=InstrumentId(Symbol("VN30F1M"), Venue("HNX")),
        client_order_id=ClientOrderId(coid),
        venue_order_id=VenueOrderId("V-1"),
        account_id=AccountId("ENTRADE-DEMO"),
        trade_id=TradeId("T-1"),
        position_id=None,
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        last_qty=Quantity.from_int(2),
        last_px=Price.from_str("1500.5"),
        currency=VND,
        commission=Money(commission, VND),
        liquidity_side=LiquiditySide.MAKER,
        event_id=UUID4(),
        ts_event=ts,
        ts_init=ts,
    )


def _nautilus_position_opened(ts: int) -> PositionOpened:
    return PositionOpened(
        trader_id=TraderId("TRADER-001"),
        strategy_id=StrategyId("BridgeStrategy-bridge"),
        instrument_id=InstrumentId(Symbol("VN30F1M"), Venue("HNX")),
        position_id=PositionId("P-1"),
        account_id=AccountId("ENTRADE-DEMO"),
        opening_order_id=ClientOrderId("bridge-1"),
        entry=OrderSide.BUY,
        side=PositionSide.LONG,
        signed_qty=2.0,
        quantity=Quantity.from_int(2),
        peak_qty=Quantity.from_int(2),
        last_qty=Quantity.from_int(2),
        last_px=Price.from_str("1500.5"),
        currency=VND,
        avg_px_open=1500.5,
        realized_pnl=Money(0.0, VND),
        event_id=UUID4(),
        ts_event=ts,
        ts_init=ts,
    )


def test_catalog_bars_and_events_roundtrip() -> None:
    """write_data -> read_research_bars / partition_streamed over a tmp catalog."""
    ts1, ts2 = _BASE - PERIOD_NS, _BASE
    bars = [_nautilus_bar(ts1, 1500.0), _nautilus_bar(ts2, 1501.0)]
    events = [
        _nautilus_submitted("bridge-1", ts1),
        _nautilus_filled("bridge-1", ts1 + 1_000, 69.0),
        _nautilus_position_opened(ts1),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        catalog = ParquetDataCatalog(tmp)
        catalog.write_data([*bars, *events])
        research = read_research_bars(catalog, BAR_TYPE, ts1 - 1, ts2 + 1)
        _assert(len(research) == 2, f"research bars={len(research)}")
        _assert(research[0].close == 1500.0, research[0])

        records = nautilus_order_records(events)
        positions = nautilus_position_records(events)
        _assert(len(records) == 2, f"order records={len(records)}")
        _assert(records[1].kind == KIND_FILLED and records[1].commission == 69.0, records[1])
        _assert(positions == [PositionRecord(ts_event_ns=ts1, signed_qty=2)], positions)

        streamed_bars, streamed_orders, streamed_positions = partition_streamed(
            [*bars, *events],
            BAR_TYPE,
            INSTRUMENT,
        )
        _assert(len(streamed_bars) == 2, "bars partitioned")
        _assert(len(streamed_orders) == 2, "orders partitioned")
        _assert(len(streamed_positions) == 1, "positions partitioned")


def test_streamed_feather_instance_dir_reads_back() -> None:
    """Handcrafted feather instance dir -> read_streamed_objects (read_live_run)."""
    ts1, ts2 = _BASE, _BASE + PERIOD_NS
    bars = [_nautilus_bar(ts1, 1500.0), _nautilus_bar(ts2, 1501.0)]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "live_root"
        instance_dir = root / "live" / "inst-1"
        instance_dir.mkdir(parents=True)
        _write_feather_batch(instance_dir, bars, Bar)
        _write_feather_batch(instance_dir, [_nautilus_submitted("bridge-1", ts1)], OrderSubmitted)
        _write_feather_batch(instance_dir, [_nautilus_filled("bridge-1", ts1 + 1_000, 69.0)], OrderFilled)
        _write_feather_batch(instance_dir, [_nautilus_position_opened(ts1)], PositionOpened)

        objects = read_streamed_objects(instance_dir)
        _assert(len(objects) == 5, f"streamed objects={len(objects)}")
        streamed_bars, streamed_orders, streamed_positions = partition_streamed(
            objects,
            BAR_TYPE,
            INSTRUMENT,
        )
        _assert(len(streamed_bars) == 2, f"bars={len(streamed_bars)}")
        _assert(len(streamed_orders) == 2, f"orders={len(streamed_orders)}")
        _assert(streamed_positions == [PositionRecord(ts_event_ns=ts1, signed_qty=2)], streamed_positions)
        _assert(streamed_orders[1].commission == 69.0, streamed_orders[1])


def _write_feather_batch(instance_dir: Path, objects: list, data_cls: type) -> None:
    batch = ArrowSerializer.serialize_batch(objects, data_cls=data_cls)
    if data_cls is Bar:
        bar_type_str = str(objects[0].bar_type)
        folder = instance_dir / class_to_filename(data_cls) / urisafe_identifier(bar_type_str)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{urisafe_identifier(bar_type_str)}_0.feather"
    else:
        path = instance_dir / f"{class_to_filename(data_cls)}_0.feather"
    with open(path, "wb") as handle:
        writer = pa.ipc.new_stream(handle, batch.schema)
        writer.write_table(batch)
        writer.close()


# --------------------------------------------------------------------------- #
# Manifest / params resolution
# --------------------------------------------------------------------------- #


def test_resolve_params_from_manifest() -> None:
    manifest = {
        "kernel": {"trader_id": "TRADER-001"},
        "strategies": [{"config": {"cooldown_secs": 7.5, "warmup_bars": 100, "force_close_dates": ["2026-09-03"]}}],
        "harness": {"cost_per_side": 0.00025},
    }
    params = resolve_params(manifest)
    _assert(params.cooldown_secs == 7.5, params.cooldown_secs)
    _assert(params.warmup_bars == 100, params.warmup_bars)
    _assert(params.force_close_dates == ["2026-09-03"], params.force_close_dates)
    _assert(params.cost_per_side == 0.00025, params.cost_per_side)
    _assert(params.buffer_bars == 8000, "defaults kept when absent")
    portfolio = build_portfolio(manifest)
    _assert(portfolio.config.harness.cost_per_side == 0.00025, portfolio.config.harness)


# --------------------------------------------------------------------------- #
# End-to-end: compute_checks over in-memory artifacts
# --------------------------------------------------------------------------- #


def test_compute_checks_full_session_pass() -> None:
    """A healthy session: warmup + 3 submits, fills in-bar, valid transitions."""
    warmup_ts = [_BASE - k * PERIOD_NS for k in range(5, 0, -1)]  # 5 warmup bars
    live_ts = [_BASE, _BASE + PERIOD_NS, _BASE + 2 * PERIOD_NS]
    warmup_closes = [1499.0 + k * 0.1 for k in range(5)]
    live_closes = [1501.0, 1502.0, 1503.0]

    decisions = [_decision(ts, ts + 1_000, "skip-warmup", close=c) for ts, c in zip(warmup_ts, warmup_closes)]
    for index, (ts, close) in enumerate(zip(live_ts, live_closes)):
        decisions.append(
            _decision(ts, ts + 1_000, "submit", target=int(round(close - 1500.0)), close=close, current=index),
        )
    decisions.sort(key=lambda d: d.ts_event_ns)

    research_warmup = [_bar(ts, close) for ts, close in zip(warmup_ts, warmup_closes)]
    research_live = [_bar(ts, close) for ts, close in zip(live_ts, live_closes)]
    streamed_bars = research_warmup + research_live

    orders: list[OrderRecord] = []
    for index, (ts, close) in enumerate(zip(live_ts, live_closes)):
        clock = ts + 1_000
        coid = f"bridge-{clock}"
        orders.append(OrderRecord(coid=coid, kind=KIND_SUBMITTED, ts_event_ns=clock))
        orders.append(
            _fill(
                coid,
                "BUY",
                1,
                close,
                ts + 2_000,
                commission=0.000229 * close * 1 * 100_000.0,
            ),
        )

    transitions = [Transition(ts_ns=_BASE - 1_000, previous="<start>", current="ACTIVE", reason="startup")]

    results, meta = compute_checks(
        decisions,
        transitions,
        research_warmup,
        research_live,
        streamed_bars,
        orders,
        position_records=[],
        params=AcceptanceParams(),
        portfolio=_StubPortfolio(),
    )
    by_name = {result.name: result for result in results}
    _assert(meta["session_day"] == "2026-09-03", meta["session_day"])
    _assert(by_name["data-parity"].status == "PASS", by_name["data-parity"].status)
    _assert(by_name["signal-parity"].status == "PASS", by_name["signal-parity"].status)
    _assert(by_name["execution"].status == "PASS", by_name["execution"].status)
    _assert(by_name["position"].status == "PASS", by_name["position"].status)
    _assert(by_name["cost"].status == "REPORT", by_name["cost"].status)
    _assert(by_name["risk"].status == "PASS", by_name["risk"].status)
    _assert(
        by_name["signal-parity"].numbers["recomputed"] == 3,
        by_name["signal-parity"].numbers,
    )


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
