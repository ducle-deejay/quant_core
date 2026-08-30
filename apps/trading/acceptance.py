"""Post-session acceptance report: six checks over one paper session's artifacts.

Consumes the milestone-1 paper session artifacts (produced by
``apps.trading.paper``) and the Nautilus research/streaming catalogs, and
writes ``acceptance.md`` + ``acceptance.json`` into the session directory:

    1. Data parity   - warmup window + session-day bars: research catalog vs
                       the streamed bars the node saw (gaps/dups/price
                       mismatches; tolerance 1 tick = 0.1 index point). The
                       session-day comparison degrades to WARN when the daily
                       ETL (16:00 local) has not landed the day yet.
    2. Signal parity - same bars -> same target: the bridge's input buffer is
                       rebuilt (catalog warmup + streamed live, dedup by
                       ts_event, capped at ``buffer_bars``) and
                       ``portfolio.compute_target`` is re-run at every decision
                       line that carried a computed target.
    3. Execution     - submit/OrderSubmitted mapping, cooldown spacing, fill
                       slippage vs the decision close, and order outcome
                       accounting (terminal states).
    4. Position      - actual position (from streamed position events, falling
                       back to fills) vs the submitted-target series; force-
                       close flatness; no working orders at session end.
    5. Cost          - report-only: actual fill commissions vs the DEC-006
                       scalar model ``cost_per_side * price * qty * 100_000``.
    6. Risk          - transition-log matrix validity and the HALTED flatten
                       circuit-breaker timing (orders submitted and filled
                       within 60 s of the halt).

Check 5 is report-only; checks 1, 2, 3, 4, 6 are gated - any FAIL makes the
process exit non-zero.

Every check is implemented as a pure function over plain records (no Nautilus
runtime objects) so the logic is unit-testable without a node; the catalog and
feather reads are thin adapters on top.

Usage (repo root; ``src`` importable):

    .venv/bin/python3 apps/trading/acceptance.py [--session-dir DIR] [--streaming-dir DIR]
        [--catalog DIR] [--bar-type STR] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, deque
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from nautilus_trader.model.data import Bar
from nautilus_trader.model.events.order import (
    OrderCanceled,
    OrderDenied,
    OrderExpired,
    OrderFilled,
    OrderRejected,
    OrderSubmitted,
)
from nautilus_trader.model.events.position import (
    PositionChanged,
    PositionClosed,
    PositionOpened,
)
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from trading.portfolio import PortfolioOrchestrator
from trading.portfolio import default_seed_portfolio_config
from trading.risk.state import HALTED
from trading.risk.state import REASON_LOSS
from trading.risk.state import REASON_STALE
from trading.strategies.bridge import WARMUP_CALENDAR_MULTIPLE
from trading.strategies.bridge import bar_period_timedelta
from trading.strategies.bridge import warmup_start

# --------------------------------------------------------------------------- #
# Constants / defaults
# --------------------------------------------------------------------------- #

#: Default session log root (bridge decisions + risk transitions).
DEFAULT_SESSIONS_DIR = "data/logs/sessions"
#: Default streaming catalog root (kernel writes under <root>/live/<instance>).
DEFAULT_STREAMING_ROOT = "data/live/live"
#: Default research ETL catalog.
DEFAULT_CATALOG_PATH = "data/catalog"
DEFAULT_BAR_TYPE = "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL"

#: DEC-006 scalar per-side fee (relative), at the 1,500 reference price.
DEFAULT_COST_PER_SIDE = 0.000229
#: VN30F1M contract multiplier (VND per index point) - OBS-009/OBS-010.
DEFAULT_CONTRACT_MULTIPLIER = 100_000.0
#: Price mismatch tolerance in index points (1 tick = 0.1 point).
PRICE_TOLERANCE = 0.1
#: Flatten circuit-breaker deadline (seconds) after a HALTED transition.
FLATTEN_WINDOW_SECS = 60.0

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
UTC = timezone.utc

#: Order-event kinds the acceptance understands.
KIND_SUBMITTED = "submitted"
KIND_FILLED = "filled"
KIND_REJECTED = "rejected"
KIND_CANCELED = "canceled"
KIND_EXPIRED = "expired"
KIND_DENIED = "denied"


# --------------------------------------------------------------------------- #
# Plain records (Nautilus-free; the checks operate on these)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BarRecord:
    """One bar as the acceptance layer sees it: open-time ts + close + volume."""

    ts_event_ns: int
    close: float
    volume: float


@dataclass(frozen=True)
class OrderRecord:
    """One order event, flattened to the fields the checks need."""

    coid: str
    kind: str  # one of KIND_*
    ts_event_ns: int
    side: str | None = None  # "BUY" | "SELL" | None
    qty: float | None = None  # last_qty for fills; quantity for submits
    price: float | None = None  # last_px for fills
    commission: float | None = None  # VND, fills only


@dataclass(frozen=True)
class PositionRecord:
    """One position event: the signed position after the event applied."""

    ts_event_ns: int
    signed_qty: int


@dataclass(frozen=True)
class Decision:
    """One decision-log line."""

    ts_event_ns: int
    clock_ns: int
    close: float | None
    target: int | None
    current_contracts: int
    action: str
    reason: str | None


@dataclass(frozen=True)
class Transition:
    """One risk transition-log line."""

    ts_ns: int
    previous: str
    current: str
    reason: str  # "" when the log carried None


@dataclass
class CheckResult:
    """One check's outcome: status + numbers + first-failure detail."""

    name: str
    status: str  # PASS | FAIL | WARN | REPORT
    numbers: dict[str, Any] = field(default_factory=dict)
    detail: str | None = None
    gated: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "gated": self.gated,
            "numbers": self.numbers,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------- #
# JSONL loaders
# --------------------------------------------------------------------------- #


def load_decisions(path: Path) -> list[Decision]:
    """Parse the bridge decision log (one JSON line per bar)."""
    records: list[Decision] = []
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON line") from exc
            records.append(
                Decision(
                    ts_event_ns=int(raw["ts_event_ns"]),
                    clock_ns=int(raw["clock_ns"]),
                    close=raw.get("close"),
                    target=raw.get("target"),
                    current_contracts=int(raw.get("current_contracts", 0)),
                    action=str(raw.get("action", "")),
                    reason=raw.get("reason"),
                ),
            )
    records.sort(key=lambda d: d.ts_event_ns)
    return records


def load_transitions(path: Path) -> list[Transition]:
    """Parse the risk overlay transition log."""
    records: list[Transition] = []
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON line") from exc
            records.append(
                Transition(
                    ts_ns=int(raw["ts_ns"]),
                    previous=str(raw.get("previous", "")),
                    current=str(raw.get("current", "")),
                    reason=raw.get("reason") or "",
                ),
            )
    return records


# --------------------------------------------------------------------------- #
# Manifest (kernel config.json inside the streaming instance dir)
# --------------------------------------------------------------------------- #

_MISSING = object()


def deep_search(obj: Any, key: str) -> Any:
    """First value for ``key`` found at any nesting depth; ``_MISSING`` if none."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = deep_search(value, key)
            if found is not _MISSING:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = deep_search(value, key)
            if found is not _MISSING:
                return found
    return _MISSING


def load_manifest(streaming_dir: Path, session_dir: Path) -> dict[str, Any]:
    """The session manifest = the kernel config.json copy in the instance dir
    (falling back to a copy in the session dir when present)."""
    for candidate in (streaming_dir / "config.json", session_dir / "config.json"):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
    return {}


@dataclass(frozen=True)
class AcceptanceParams:
    """Resolved session parameters (manifest overrides + defaults)."""

    warmup_bars: int = 7200
    buffer_bars: int = 8000
    cooldown_secs: float = 5.0
    min_gap_contracts: int = 1
    client_order_id_prefix: str = "bridge"
    force_close_dates: list[str] = field(default_factory=list)
    force_close_local_time: str = "14:00"
    cost_per_side: float = DEFAULT_COST_PER_SIDE
    contract_multiplier: float = DEFAULT_CONTRACT_MULTIPLIER
    bar_type: str = DEFAULT_BAR_TYPE


def resolve_params(manifest: dict[str, Any], *, bar_type: str | None = None) -> AcceptanceParams:
    """Project manifest values (deep-searched) onto ``AcceptanceParams``."""
    warmup_bars = deep_search(manifest, "warmup_bars")
    buffer_bars = deep_search(manifest, "buffer_bars")
    cooldown_secs = deep_search(manifest, "cooldown_secs")
    min_gap = deep_search(manifest, "min_gap_contracts")
    prefix = deep_search(manifest, "client_order_id_prefix")
    dates = deep_search(manifest, "force_close_dates")
    fc_time = deep_search(manifest, "force_close_local_time")
    cost = deep_search(manifest, "cost_per_side")
    multiplier = deep_search(manifest, "contract_multiplier")
    manifest_bar_type = deep_search(manifest, "bar_type")
    resolved_bar_type = bar_type
    if resolved_bar_type is None and manifest_bar_type is not _MISSING:
        resolved_bar_type = manifest_bar_type
    return AcceptanceParams(
        warmup_bars=int(warmup_bars) if isinstance(warmup_bars, (int, float)) else 7200,
        buffer_bars=int(buffer_bars) if isinstance(buffer_bars, (int, float)) else 8000,
        cooldown_secs=float(cooldown_secs) if isinstance(cooldown_secs, (int, float)) else 5.0,
        min_gap_contracts=int(min_gap) if isinstance(min_gap, (int, float)) else 1,
        client_order_id_prefix=str(prefix) if isinstance(prefix, str) else "bridge",
        force_close_dates=list(dates) if isinstance(dates, list) else [],
        force_close_local_time=str(fc_time) if isinstance(fc_time, str) else "14:00",
        cost_per_side=float(cost) if isinstance(cost, (int, float)) else DEFAULT_COST_PER_SIDE,
        contract_multiplier=(
            float(multiplier) if isinstance(multiplier, (int, float)) else DEFAULT_CONTRACT_MULTIPLIER
        ),
        bar_type=str(resolved_bar_type) if resolved_bar_type else DEFAULT_BAR_TYPE,
    )


def build_portfolio(manifest: dict[str, Any]) -> PortfolioOrchestrator:
    """The live portfolio (seed config, overridden from the manifest when present)."""
    config = default_seed_portfolio_config()
    overrides: dict[str, Any] = {}
    for key in ("capital_vnd", "max_contracts", "margin_rate", "safety_factor", "vol_target"):
        value = deep_search(manifest, key)
        if value is not None and isinstance(value, (int, float)):
            overrides[key] = value
    expressions = deep_search(manifest, "expressions")
    weights = deep_search(manifest, "weights")
    if isinstance(expressions, list) and isinstance(weights, list) and expressions:
        overrides["expressions"] = tuple(str(e) for e in expressions)
        overrides["weights"] = tuple(float(w) for w in weights)
    harness_cost = deep_search(manifest, "cost_per_side")
    if isinstance(harness_cost, (int, float)):
        overrides["harness"] = replace(config.harness, cost_per_side=float(harness_cost))
    if overrides:
        config = replace(config, **overrides)
    return PortfolioOrchestrator(config=config)


# --------------------------------------------------------------------------- #
# Nautilus -> plain-record adapters
# --------------------------------------------------------------------------- #


def nautilus_bar_to_record(bar: Bar) -> BarRecord:
    return BarRecord(
        ts_event_ns=int(bar.ts_event),
        close=float(bar.close.as_double()),
        volume=float(bar.volume.as_double()),
    )


def _order_record_from_event(event: Any) -> OrderRecord | None:
    if isinstance(event, OrderSubmitted):
        return OrderRecord(
            coid=event.client_order_id.value,
            kind=KIND_SUBMITTED,
            ts_event_ns=int(event.ts_event),
            side=event.order_side.name if hasattr(event, "order_side") else None,
            qty=float(event.quantity.as_double()) if hasattr(event, "quantity") else None,
        )
    if isinstance(event, OrderFilled):
        return OrderRecord(
            coid=event.client_order_id.value,
            kind=KIND_FILLED,
            ts_event_ns=int(event.ts_event),
            side=event.order_side.name,
            qty=float(event.last_qty.as_double()),
            price=float(event.last_px.as_double()),
            commission=float(event.commission.as_double()),
        )
    if isinstance(event, OrderRejected):
        return OrderRecord(coid=event.client_order_id.value, kind=KIND_REJECTED, ts_event_ns=int(event.ts_event))
    if isinstance(event, OrderCanceled):
        return OrderRecord(coid=event.client_order_id.value, kind=KIND_CANCELED, ts_event_ns=int(event.ts_event))
    if isinstance(event, OrderExpired):
        return OrderRecord(coid=event.client_order_id.value, kind=KIND_EXPIRED, ts_event_ns=int(event.ts_event))
    if isinstance(event, OrderDenied):
        return OrderRecord(coid=event.client_order_id.value, kind=KIND_DENIED, ts_event_ns=int(event.ts_init))
    return None


def nautilus_order_records(objects: list[Any]) -> list[OrderRecord]:
    """Flatten every recognized order event from a streamed object list."""
    records = []
    for obj in objects:
        record = _order_record_from_event(obj)
        if record is not None:
            records.append(record)
    return records


def nautilus_position_records(objects: list[Any]) -> list[PositionRecord]:
    """Position series from streamed position events (signed position after each)."""
    records = []
    for obj in objects:
        if isinstance(obj, (PositionOpened, PositionChanged, PositionClosed)):
            records.append(
                PositionRecord(
                    ts_event_ns=int(obj.ts_event),
                    signed_qty=int(round(float(obj.signed_qty))),
                ),
            )
    return records


def position_series_from_fills(fills: list[OrderRecord]) -> list[PositionRecord]:
    """Fallback position series: accumulate signed fill quantities from 0."""
    series: list[PositionRecord] = []
    position = 0
    for fill in sorted(fills, key=lambda f: f.ts_event_ns):
        sign = 1 if fill.side == "BUY" else -1
        position += sign * int(round(fill.qty or 0.0))
        series.append(PositionRecord(ts_event_ns=fill.ts_event_ns, signed_qty=position))
    return series


def position_after(series: list[PositionRecord], ts_ns: int) -> int:
    """Signed position after all events with ``ts_event_ns <= ts_ns`` (0 if none)."""
    position = 0
    for record in series:
        if record.ts_event_ns <= ts_ns:
            position = record.signed_qty
        else:
            break
    return position


def position_before(series: list[PositionRecord], ts_ns: int) -> int:
    """Signed position after all events strictly before ``ts_ns``."""
    position = 0
    for record in series:
        if record.ts_event_ns < ts_ns:
            position = record.signed_qty
        else:
            break
    return position


def order_terminal_states(orders: list[OrderRecord]) -> dict[str, str]:
    """One terminal state per client order id.

    Precedence (an order with multiple terminal events counts under the first
    match): rejected, denied, canceled, expired, then filled (any fill and no
    other terminal event). Orders with no terminal event are ``"working"``.
    """
    precedence = [KIND_REJECTED, KIND_DENIED, KIND_CANCELED, KIND_EXPIRED]
    states: dict[str, str] = {}
    has_fill: set[str] = set()
    for order in orders:
        if order.kind == KIND_FILLED:
            has_fill.add(order.coid)
        elif order.kind in precedence:
            states.setdefault(order.coid, order.kind)
    for coid in has_fill:
        states.setdefault(coid, KIND_FILLED)
    for order in orders:
        if order.kind == KIND_SUBMITTED:
            states.setdefault(order.coid, "working")
    return states


# --------------------------------------------------------------------------- #
# Catalog / streaming adapters
# --------------------------------------------------------------------------- #


def read_research_bars(
    catalog: ParquetDataCatalog,
    bar_type: str,
    start_ns: int,
    end_ns: int,
) -> list[BarRecord]:
    """Research catalog bars in ``[start_ns, end_ns)`` (ts_init filter)."""
    start = pd.Timestamp(start_ns, unit="ns", tz="UTC")
    end = pd.Timestamp(end_ns, unit="ns", tz="UTC")
    bars = catalog.bars(bar_types=[bar_type], start=start, end=end)
    return sorted(
        (nautilus_bar_to_record(bar) for bar in bars),
        key=lambda b: b.ts_event_ns,
    )


def read_streamed_objects(streaming_dir: Path) -> list[Any]:
    """All Nautilus objects streamed into one session instance directory.

    The instance dir sits at ``<catalog_path>/live/<instance_id>`` (the kernel
    writes under ``<catalog_path>/<environment>/<instance_id>``); the feather
    files are read through the standard ``read_live_run`` API, so the catalog
    root is the instance dir's grandparent.
    """
    root = streaming_dir.parents[1]
    instance_id = streaming_dir.name
    catalog = ParquetDataCatalog(str(root))
    objects = catalog.read_live_run(instance_id)
    return list(objects)


def partition_streamed(
    objects: list[Any],
    bar_type: str,
    instrument_id: str,
) -> tuple[list[BarRecord], list[OrderRecord], list[PositionRecord]]:
    """Split streamed objects into bars/orders/positions for this instrument."""
    bars: list[BarRecord] = []
    orders: list[OrderRecord] = []
    positions: list[PositionRecord] = []
    for obj in objects:
        if isinstance(obj, Bar):
            if str(obj.bar_type) != bar_type:
                continue
            bars.append(nautilus_bar_to_record(obj))
        elif isinstance(obj, (OrderSubmitted, OrderFilled, OrderRejected, OrderCanceled, OrderExpired, OrderDenied)):
            if str(obj.instrument_id) != instrument_id:
                continue
            record = _order_record_from_event(obj)
            if record is not None:
                orders.append(record)
        elif isinstance(obj, (PositionOpened, PositionChanged, PositionClosed)):
            if str(obj.instrument_id) != instrument_id:
                continue
            positions.append(
                PositionRecord(
                    ts_event_ns=int(obj.ts_event),
                    signed_qty=int(round(float(obj.signed_qty))),
                ),
            )
    bars.sort(key=lambda b: b.ts_event_ns)
    orders.sort(key=lambda o: o.ts_event_ns)
    positions.sort(key=lambda p: p.ts_event_ns)
    return bars, orders, positions


# --------------------------------------------------------------------------- #
# Check 1 - data parity
# --------------------------------------------------------------------------- #


def _compare_window(research: list[BarRecord], streamed: list[BarRecord]) -> dict[str, Any]:
    research_by_ts = {b.ts_event_ns: b for b in research}
    streamed_by_ts = {b.ts_event_ns: b for b in streamed}
    research_ts = set(research_by_ts)
    streamed_ts = set(streamed_by_ts)
    gaps = sorted(research_ts - streamed_ts)
    dup_ts = sorted(ts for ts, count in Counter(b.ts_event_ns for b in streamed).items() if count > 1)
    price_mismatches = []
    for ts in sorted(research_ts & streamed_ts):
        streamed_close = streamed_by_ts[ts].close
        research_close = research_by_ts[ts].close
        if abs(streamed_close - research_close) > PRICE_TOLERANCE:
            price_mismatches.append((ts, streamed_close, research_close))
    return {
        "research_bars": len(research),
        "streamed_bars": len(streamed),
        "gaps": len(gaps),
        "dups": len(dup_ts),
        "price_mismatches": len(price_mismatches),
        "first_gap_ts_ns": gaps[0] if gaps else None,
        "first_dup_ts_ns": dup_ts[0] if dup_ts else None,
        "first_price_mismatch": (
            {"ts_event_ns": price_mismatches[0][0], "streamed_close": price_mismatches[0][1], "research_close": price_mismatches[0][2]}
            if price_mismatches
            else None
        ),
    }


def check_data_parity(
    research_warmup: list[BarRecord],
    streamed_warmup: list[BarRecord],
    research_live: list[BarRecord],
    streamed_live: list[BarRecord],
    *,
    live_catalog_pending: bool,
) -> CheckResult:
    """Checks 1: warmup strict; session-day WARN when the ETL is pending."""
    warmup = _compare_window(research_warmup, streamed_warmup)
    live = _compare_window(research_live, streamed_live)
    live["catalog_pending"] = live_catalog_pending

    warmup_clean = warmup["gaps"] == 0 and warmup["dups"] == 0 and warmup["price_mismatches"] == 0
    live_clean = live["gaps"] == 0 and live["dups"] == 0 and live["price_mismatches"] == 0

    if not warmup_clean:
        status = "FAIL"
        detail = (
            f"warmup window: {warmup['gaps']} gaps, {warmup['dups']} dups, "
            f"{warmup['price_mismatches']} price mismatches "
            f"(first gap ts={warmup['first_gap_ts_ns']}, "
            f"first dup ts={warmup['first_dup_ts_ns']})"
        )
    elif live_catalog_pending:
        status = "WARN"
        detail = (
            "research catalog lacks the session day (daily ETL runs at 16:00 "
            "local); live-window comparison skipped, warmup checked strictly"
        )
    elif not live_clean:
        status = "FAIL"
        detail = (
            f"session-day window: {live['gaps']} gaps, {live['dups']} dups, "
            f"{live['price_mismatches']} price mismatches "
            f"(first gap ts={live['first_gap_ts_ns']})"
        )
    else:
        status = "PASS"
        detail = None
    return CheckResult(
        name="data-parity",
        status=status,
        numbers={"warmup": warmup, "live": live},
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# Check 2 - signal parity
# --------------------------------------------------------------------------- #


def rebuild_snapshots(
    warmup: list[BarRecord],
    live: list[BarRecord],
    buffer_bars: int,
) -> dict[int, dict[str, list[float]]]:
    """Rebuild the bridge's rolling input buffer per bar (mirror ``_append_bar``:
    dedup by ts_event, cap at ``buffer_bars``). Returns ts -> snapshot."""
    closes: deque[float] = deque(maxlen=buffer_bars)
    volumes: deque[float] = deque(maxlen=buffer_bars)
    last_ts: int | None = None
    snapshots: dict[int, dict[str, list[float]]] = {}
    merged = sorted(warmup + live, key=lambda b: b.ts_event_ns)
    for bar in merged:
        if last_ts is not None and bar.ts_event_ns <= last_ts:
            continue
        last_ts = bar.ts_event_ns
        closes.append(bar.close)
        volumes.append(bar.volume)
        snapshots[bar.ts_event_ns] = {
            "close": list(closes),
            "volume": list(volumes),
        }
    return snapshots


def check_signal_parity(
    decisions: list[Decision],
    warmup: list[BarRecord],
    live: list[BarRecord],
    portfolio: Any,
    buffer_bars: int,
) -> CheckResult:
    """Checks 2: recomputed target must equal the logged target on every line."""
    snapshots = rebuild_snapshots(warmup, live, buffer_bars)
    diffs: list[dict[str, Any]] = []
    missing: list[int] = []
    recomputed = 0
    for decision in decisions:
        if decision.target is None:
            continue
        ts = decision.ts_event_ns
        snapshot = snapshots.get(ts)
        if snapshot is None:
            missing.append(ts)
            continue
        recomputed += 1
        now = datetime.fromtimestamp(decision.clock_ns / 1e9, tz=UTC)
        result = portfolio.compute_target(snapshot, now)
        if result.target_contracts != decision.target:
            diffs.append(
                {
                    "ts_event_ns": ts,
                    "clock_ns": decision.clock_ns,
                    "action": decision.action,
                    "logged_target": decision.target,
                    "recomputed_target": result.target_contracts,
                    "close": snapshot["close"][-1],
                    "recompute_reason": result.reason,
                },
            )
    first = diffs[0] if diffs else None
    status = "PASS" if not diffs and not missing else "FAIL"
    detail = None
    if diffs:
        detail = (
            f"first diff at ts={first['ts_event_ns']} action={first['action']}: "
            f"logged target {first['logged_target']} vs recomputed {first['recomputed_target']} "
            f"(close={first['close']}, reason={first['recompute_reason']})"
        )
    elif missing:
        detail = f"{len(missing)} decision bars not found in the rebuilt sequence"
    return CheckResult(
        name="signal-parity",
        status=status,
        numbers={
            "recomputed": recomputed,
            "diffs": len(diffs),
            "decision_bars_missing": len(missing),
            "first_diff": first,
            "missing_ts": missing[:10],
        },
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# Check 3 - execution
# --------------------------------------------------------------------------- #


def check_execution(
    decisions: list[Decision],
    orders: list[OrderRecord],
    *,
    cooldown_secs: float,
    client_order_id_prefix: str,
) -> CheckResult:
    """Checks 3: submit mapping, cooldown, slippage, outcome accounting."""
    submits = [d for d in decisions if d.action == "submit"]
    prefix = f"{client_order_id_prefix}-"
    submit_by_coid = {f"{client_order_id_prefix}-{d.clock_ns}": d for d in submits}
    submitted_events = [o for o in orders if o.kind == KIND_SUBMITTED and o.coid.startswith(prefix)]
    submitted_coids = {o.coid for o in submitted_events}

    missing_coids = sorted(set(submit_by_coid) - submitted_coids)
    extra_coids = sorted(submitted_coids - set(submit_by_coid))

    # (a) one OrderSubmitted per submit decision.
    mapping_ok = not missing_coids and not extra_coids and len(submits) == len(submitted_events)

    # (b) cooldown spacing between consecutive submits (clock_ns).
    clocks = sorted(d.clock_ns for d in submits)
    gaps_ns = [b - a for a, b in zip(clocks, clocks[1:])]
    cooldown_ns = cooldown_secs * 1_000_000_000
    cooldown_violations = [g for g in gaps_ns if g < cooldown_ns]

    # (c) slippage per fill vs the decision-log close at the submit.
    fills = [o for o in orders if o.kind == KIND_FILLED]
    slippages: list[dict[str, Any]] = []
    for fill in fills:
        decision = submit_by_coid.get(fill.coid)
        if decision is None or decision.close is None:
            continue
        slippages.append(
            {
                "coid": fill.coid,
                "fill_price": fill.price,
                "decision_close": decision.close,
                "slippage": fill.price - decision.close,
                "ts_event_ns": fill.ts_event_ns,
            },
        )
    signed = [s["slippage"] for s in slippages]
    abs_values = [abs(v) for v in signed]

    # (d) every order outcome accounted (order-level terminal states; all
    # submitted orders in the session, bridge + overlay flatten orders alike).
    all_submitted = [o for o in orders if o.kind == KIND_SUBMITTED]
    terminal = Counter(order_terminal_states(orders).values())
    accounted = (
        terminal.get(KIND_FILLED, 0)
        + terminal.get(KIND_REJECTED, 0)
        + terminal.get(KIND_CANCELED, 0)
        + terminal.get(KIND_EXPIRED, 0)
        + terminal.get(KIND_DENIED, 0)
    )
    working = terminal.get("working", 0)
    outcome_difference = len(all_submitted) - accounted

    failures = []
    if not mapping_ok:
        failures.append(
            f"submit mapping: {len(submits)} submits vs {len(submitted_events)} "
            f"OrderSubmitted events ({len(missing_coids)} missing, {len(extra_coids)} extra coids)",
        )
    if cooldown_violations:
        failures.append(f"{len(cooldown_violations)} cooldown violations")
    if outcome_difference != 0:
        failures.append(
            f"order outcome accounting: {len(all_submitted)} submitted vs "
            f"{accounted} terminal ({working} still working; difference {outcome_difference})",
        )
    status = "PASS" if not failures else "FAIL"
    return CheckResult(
        name="execution",
        status=status,
        numbers={
            "submits": len(submits),
            "order_submitted_events": len(submitted_events),
            "matched": len(submitted_coids & set(submit_by_coid)),
            "missing_coids": missing_coids[:10],
            "extra_coids": extra_coids[:10],
            "cooldown_secs": cooldown_secs,
            "min_submit_gap_ns": min(gaps_ns) if gaps_ns else None,
            "cooldown_violations": len(cooldown_violations),
            "slippage_count": len(slippages),
            "slippage_mean": (sum(signed) / len(signed)) if signed else None,
            "slippage_max": max(signed) if signed else None,
            "slippage_abs_mean": (sum(abs_values) / len(abs_values)) if abs_values else None,
            "slippage_abs_max": max(abs_values) if abs_values else None,
            "terminal": dict(terminal),
            "outcome_difference": outcome_difference,
        },
        detail=failures[0] if failures else None,
    )


# --------------------------------------------------------------------------- #
# Check 4 - position
# --------------------------------------------------------------------------- #


def check_position(
    decisions: list[Decision],
    position_series: list[PositionRecord],
    orders: list[OrderRecord],
    *,
    bar_period_ns: int,
) -> CheckResult:
    """Checks 4: target following, force-close flatness, no working orders."""
    submits = [d for d in decisions if d.action == "submit"]

    # Working target after each submit; a force-close overrides the target to
    # flat (the bridge's effective target for the rest of the day is 0).
    working_target = 0
    target_by_ts: dict[int, int] = {}
    for decision in decisions:
        if decision.action == "force-close":
            working_target = 0
        elif decision.action == "submit" and decision.target is not None:
            working_target = decision.target
        target_by_ts[decision.ts_event_ns] = working_target

    deviations: list[tuple[int, int, int]] = []
    for decision in decisions:
        pos = position_after(series=position_series, ts_ns=decision.ts_event_ns + bar_period_ns - 1)
        deviations.append((decision.ts_event_ns, pos, target_by_ts[decision.ts_event_ns]))
    max_deviation = max((abs(pos - target) for _, pos, target in deviations), default=0)
    deviation_bars_over_1 = sum(1 for _, pos, target in deviations if abs(pos - target) > 1)

    # Reach check: after each submit, the position must reach the target before
    # the next submit's bar (a fill point inside the window satisfies it).
    unreached: list[dict[str, Any]] = []
    for index, submit in enumerate(submits):
        window_end = submits[index + 1].ts_event_ns if index + 1 < len(submits) else None
        target = submit.target if submit.target is not None else 0
        reached = False
        for point_ts, point_pos in ((r.ts_event_ns, r.signed_qty) for r in position_series):
            if point_ts < submit.ts_event_ns:
                continue
            if window_end is not None and point_ts >= window_end:
                break
            if point_pos == target:
                reached = True
                break
        if not reached:
            unreached.append(
                {"ts_event_ns": submit.ts_event_ns, "target": target, "next_submit_ts": window_end},
            )

    # (b) force-close day: final position must be flat.
    has_force_close = any(d.action == "force-close" for d in decisions)
    final_position = position_series[-1].signed_qty if position_series else 0

    # (c) no working order at session end.
    working_at_end = sum(1 for state in order_terminal_states(orders).values() if state == "working")

    failures = []
    if max_deviation > 1:
        failures.append(
            f"position deviates from target by up to {max_deviation} contracts "
            f"({deviation_bars_over_1} bars > 1)",
        )
    if unreached:
        failures.append(f"{len(unreached)} submit targets never reached before the next submit")
    if has_force_close and final_position != 0:
        failures.append(f"force-close day: final position {final_position} not flat")
    if working_at_end:
        failures.append(f"{working_at_end} working order(s) at session end")
    status = "PASS" if not failures else "FAIL"
    return CheckResult(
        name="position",
        status=status,
        numbers={
            "max_deviation_contracts": max_deviation,
            "deviation_bars_over_1": deviation_bars_over_1,
            "submits": len(submits),
            "targets_unreached": len(unreached),
            "unreached": unreached[:5],
            "force_close_action": has_force_close,
            "final_position": final_position,
            "working_orders_at_end": working_at_end,
        },
        detail=failures[0] if failures else None,
    )


# --------------------------------------------------------------------------- #
# Check 5 - cost (report-only)
# --------------------------------------------------------------------------- #


def check_cost(
    orders: list[OrderRecord],
    *,
    cost_per_side: float,
    contract_multiplier: float,
) -> CheckResult:
    """Checks 5: actual fill commissions vs the DEC-006 scalar model fee."""
    fills = [o for o in orders if o.kind == KIND_FILLED and o.price is not None and o.qty is not None]
    per_fill: list[dict[str, Any]] = []
    total_actual = 0.0
    total_model = 0.0
    relative_diffs: list[float] = []
    for fill in fills:
        notional = fill.price * fill.qty * contract_multiplier
        model_fee = cost_per_side * notional
        actual = fill.commission or 0.0
        total_actual += actual
        total_model += model_fee
        if model_fee > 0:
            relative_diffs.append((actual - model_fee) / model_fee)
        per_fill.append(
            {
                "coid": fill.coid,
                "qty": fill.qty,
                "price": fill.price,
                "actual_commission_vnd": actual,
                "model_fee_vnd": model_fee,
                "diff_vnd": actual - model_fee,
            },
        )
    mean_relative = sum(relative_diffs) / len(relative_diffs) if relative_diffs else None
    mean_abs_relative = (
        sum(abs(d) for d in relative_diffs) / len(relative_diffs) if relative_diffs else None
    )
    return CheckResult(
        name="cost",
        status="REPORT",  # first calibration point of the 7->1 loop; not gated
        gated=False,
        numbers={
            "fills": len(fills),
            "total_actual_vnd": total_actual,
            "total_model_vnd": total_model,
            "diff_vnd": total_actual - total_model,
            "mean_relative_diff": mean_relative,
            "mean_abs_relative_diff": mean_abs_relative,
            "cost_per_side": cost_per_side,
            "contract_multiplier": contract_multiplier,
            "per_fill": per_fill,
        },
        detail=None,
    )


# --------------------------------------------------------------------------- #
# Check 6 - risk
# --------------------------------------------------------------------------- #

#: Allowed (previous, current) -> reasons; reason "" means empty/None.
_VALID_TRANSITIONS: dict[tuple[str, str], set[str]] = {
    ("<start>", "ACTIVE"): {"startup"},
    ("<start>", "REDUCING"): {"startup"},
    ("<start>", "HALTED"): {"startup"},
    ("ACTIVE", "ACTIVE"): {""},
    ("ACTIVE", "REDUCING"): {"exposure-cap"},
    ("ACTIVE", "HALTED"): {"intraday-loss-limit", "stale-feed"},
    ("REDUCING", "ACTIVE"): {""},
    ("REDUCING", "REDUCING"): {"exposure-cap"},
    ("REDUCING", "HALTED"): {"intraday-loss-limit", "stale-feed"},
    ("HALTED", "ACTIVE"): {""},
    ("HALTED", "REDUCING"): {"exposure-cap"},
    ("HALTED", "HALTED"): {"intraday-loss-limit", "stale-feed"},
}


def check_risk(
    transitions: list[Transition],
    position_series: list[PositionRecord],
    orders: list[OrderRecord],
    *,
    flatten_window_secs: float = FLATTEN_WINDOW_SECS,
) -> CheckResult:
    """Checks 6: transition matrix validity + HALTED flatten timing."""
    invalid: list[dict[str, Any]] = []
    for index, transition in enumerate(transitions):
        allowed_reasons = _VALID_TRANSITIONS.get((transition.previous, transition.current))
        if allowed_reasons is None or transition.reason not in allowed_reasons:
            invalid.append(
                {
                    "index": index,
                    "ts_ns": transition.ts_ns,
                    "previous": transition.previous,
                    "current": transition.current,
                    "reason": transition.reason,
                },
            )

    halted = [
        t for t in transitions if t.current == HALTED and t.reason in (REASON_LOSS, REASON_STALE)
    ]
    window_ns = int(flatten_window_secs * 1_000_000_000)
    flatten_failures: list[dict[str, Any]] = []
    flatten_times: list[float] = []
    flatten_ok = 0
    for transition in halted:
        position_at_halt = position_after(position_series, transition.ts_ns)
        if position_at_halt == 0:
            flatten_ok += 1  # nothing to flatten; vacuous pass
            flatten_times.append(0.0)
            continue
        window_fills = [
            o
            for o in orders
            if o.kind == KIND_FILLED
            and o.ts_event_ns >= transition.ts_ns
            and o.ts_event_ns < transition.ts_ns + window_ns
        ]
        window_submits = [
            o
            for o in orders
            if o.kind == KIND_SUBMITTED
            and o.ts_event_ns >= transition.ts_ns
            and o.ts_event_ns < transition.ts_ns + window_ns
        ]
        cumulative = 0
        flat_at_ns: int | None = None
        for fill in sorted(window_fills, key=lambda o: o.ts_event_ns):
            sign = 1 if fill.side == "BUY" else -1
            cumulative += sign * int(round(fill.qty or 0.0))
            if cumulative == -position_at_halt:
                flat_at_ns = fill.ts_event_ns
                break
        if window_submits and cumulative == -position_at_halt and flat_at_ns is not None:
            flatten_ok += 1
            flatten_times.append((flat_at_ns - transition.ts_ns) / 1e9)
        else:
            flatten_failures.append(
                {
                    "ts_ns": transition.ts_ns,
                    "reason": transition.reason,
                    "position_at_halt": position_at_halt,
                    "fills_in_window": len(window_fills),
                    "submits_in_window": len(window_submits),
                    "signed_fill_sum": cumulative,
                },
            )

    failures = []
    if invalid:
        first = invalid[0]
        failures.append(
            f"invalid transition at index {first['index']}: "
            f"{first['previous']} -> {first['current']} reason={first['reason']!r}",
        )
    if flatten_failures:
        first = flatten_failures[0]
        failures.append(
            f"flatten did not complete within {flatten_window_secs}s of the HALTED "
            f"transition at ts={first['ts_ns']} (position {first['position_at_halt']}, "
            f"signed fills in window {first['signed_fill_sum']})",
        )
    status = "PASS" if not failures else "FAIL"
    return CheckResult(
        name="risk",
        status=status,
        numbers={
            "transitions": len(transitions),
            "invalid_transitions": len(invalid),
            "invalid": invalid[:5],
            "halted_events": len(halted),
            "flatten_ok": flatten_ok,
            "flatten_fail": len(flatten_failures),
            "flatten_times_secs": flatten_times,
            "flatten_failures": flatten_failures[:5],
        },
        detail=failures[0] if failures else None,
    )


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #


def write_reports(
    session_dir: Path,
    results: list[CheckResult],
    meta: dict[str, Any],
    exit_code: int,
) -> None:
    """Write ``acceptance.json`` + ``acceptance.md`` into ``session_dir``."""
    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "session_dir": str(session_dir),
        "meta": meta,
        "checks": [result.to_dict() for result in results],
        "exit_code": exit_code,
    }
    json_path = session_dir / "acceptance.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Session Acceptance Report",
        "",
        f"- session dir: `{meta.get('session_dir', '')}`",
        f"- streaming dir: `{meta.get('streaming_dir', '')}`",
        f"- research catalog: `{meta.get('catalog_path', '')}`",
        f"- bar type: `{meta.get('bar_type', '')}`",
        f"- generated: {payload['generated_at_utc']}",
        f"- exit code: {exit_code}",
        "",
    ]
    for result in results:
        lines.append(f"## {result.name} - {result.status}" + ("" if result.gated else " (report-only)"))
        lines.append("")
        if result.detail:
            lines.append(f"- detail: {result.detail}")
        for key, value in sorted(result.numbers.items()):
            lines.append(f"- {key}: {json.dumps(value, default=str)}")
        lines.append("")
    md_path = session_dir / "acceptance.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Session resolution
# --------------------------------------------------------------------------- #


def latest_session_dir(base: Path) -> Path:
    """Newest session directory (by decisions.jsonl mtime) under ``base``."""
    if not base.is_dir():
        raise FileNotFoundError(f"session root not found: {base}")
    candidates = [p for p in base.iterdir() if p.is_dir() and (p / "decisions.jsonl").exists()]
    if not candidates:
        raise FileNotFoundError(f"no session with decisions.jsonl under {base}")
    return max(candidates, key=lambda p: (p / "decisions.jsonl").stat().st_mtime)


def resolve_streaming_dir(streaming_dir: Path) -> Path:
    """Normalize a streaming path to the instance dir (``<root>/live/<id>``)."""
    if (streaming_dir / "live").is_dir():
        base = streaming_dir / "live"
        candidates = [p for p in base.iterdir() if p.is_dir()]
        if not candidates:
            raise FileNotFoundError(f"no live instances under {base}")
        return max(candidates, key=lambda p: p.stat().st_mtime)
    if not streaming_dir.is_dir():
        raise FileNotFoundError(f"streaming instance dir not found: {streaming_dir}")
    return streaming_dir


def latest_streaming_instance(base: Path) -> Path:
    """Newest instance directory under the default ``data/live/live`` root."""
    if not base.is_dir():
        raise FileNotFoundError(f"streaming root not found: {base}")
    candidates = [p for p in base.iterdir() if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"no live instances under {base}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def compute_checks(
    decisions: list[Decision],
    transitions: list[Transition],
    research_warmup: list[BarRecord],
    research_live: list[BarRecord],
    streamed_bars: list[BarRecord],
    order_records: list[OrderRecord],
    position_records: list[PositionRecord],
    params: AcceptanceParams,
    portfolio: Any,
) -> tuple[list[CheckResult], dict[str, Any]]:
    """Run all six checks over the loaded artifacts (pure; no catalog reads)."""
    instrument_id = params.bar_type.split("-", 1)[0]
    meta: dict[str, Any] = {
        "bar_type": params.bar_type,
        "instrument_id": instrument_id,
        "params": {
            "warmup_bars": params.warmup_bars,
            "buffer_bars": params.buffer_bars,
            "cooldown_secs": params.cooldown_secs,
            "client_order_id_prefix": params.client_order_id_prefix,
            "cost_per_side": params.cost_per_side,
            "contract_multiplier": params.contract_multiplier,
        },
    }
    if not decisions:
        raise ValueError("decision log is empty")

    # Session start + warmup request window (mirror bridge.warmup_start).
    session_start_ns = min(d.clock_ns for d in decisions)
    session_start_dt = datetime.fromtimestamp(session_start_ns / 1e9, tz=UTC)
    warmup_start_dt = warmup_start(
        session_start_dt,
        params.bar_type,
        params.warmup_bars,
        WARMUP_CALENDAR_MULTIPLE,
    )
    warmup_start_ns = int(warmup_start_dt.timestamp() * 1e9)

    # Session day (VN) from the decision log: first bar past warmup, else last.
    live_decisions = [d for d in decisions if d.action != "skip-warmup"]
    boundary = live_decisions[0].ts_event_ns if live_decisions else decisions[-1].ts_event_ns
    session_day_ref = live_decisions[-1] if live_decisions else decisions[-1]
    session_day = (
        datetime.fromtimestamp(session_day_ref.ts_event_ns / 1e9, tz=UTC)
        .astimezone(VN_TZ)
        .date()
    )
    day_start_vn = datetime(session_day.year, session_day.month, session_day.day, tzinfo=VN_TZ)
    day_start_ns = int(day_start_vn.astimezone(UTC).timestamp() * 1e9)
    day_end_ns = day_start_ns + 24 * 3600 * 1_000_000_000
    meta["session_day"] = session_day.isoformat()

    # The warmup window ends at the last warmup bar (the first live bar), so
    # every bar the bridge served during warmup is inside the comparison.
    warmup_window_end_ns = boundary
    # The session-day live window ends at the last bar the node processed, so
    # a session that stopped early is not penalized for bars it never reached.
    last_seen_ns = decisions[-1].ts_event_ns
    live_window_end_ns = min(day_end_ns, last_seen_ns + 1)
    live_catalog_pending = len(research_live) == 0

    if not position_records:
        fills = [o for o in order_records if o.kind == KIND_FILLED]
        position_records = position_series_from_fills(fills)

    # Warmup/live split for the rebuild: the first non-warmup decision bar.
    warmup_input = research_warmup + [b for b in streamed_bars if b.ts_event_ns < boundary]
    live_input = [b for b in streamed_bars if b.ts_event_ns >= boundary]

    streamed_warmup = [b for b in streamed_bars if warmup_start_ns <= b.ts_event_ns < warmup_window_end_ns]
    streamed_live = [b for b in streamed_bars if day_start_ns <= b.ts_event_ns < live_window_end_ns]

    bar_period_ns = int(bar_period_timedelta(params.bar_type).total_seconds() * 1e9)

    results = [
        check_data_parity(
            research_warmup,
            streamed_warmup,
            research_live,
            streamed_live,
            live_catalog_pending=live_catalog_pending,
        ),
        check_signal_parity(
            decisions,
            warmup_input,
            live_input,
            portfolio,
            params.buffer_bars,
        ),
        check_execution(
            decisions,
            order_records,
            cooldown_secs=params.cooldown_secs,
            client_order_id_prefix=params.client_order_id_prefix,
        ),
        check_position(
            decisions,
            position_records,
            order_records,
            bar_period_ns=bar_period_ns,
        ),
        check_cost(
            order_records,
            cost_per_side=params.cost_per_side,
            contract_multiplier=params.contract_multiplier,
        ),
        check_risk(transitions, position_records, order_records),
    ]
    return results, meta


def run_acceptance(
    session_dir: Path,
    streaming_dir: Path,
    catalog_path: Path,
    params: AcceptanceParams,
    portfolio: Any,
) -> tuple[list[CheckResult], dict[str, Any]]:
    """Load the artifacts (JSONL logs + research/streaming catalogs) and run
    all six checks. Returns (results, meta)."""
    decisions_path = session_dir / "decisions.jsonl"
    transitions_path = session_dir / "risk_transitions.jsonl"
    if not decisions_path.exists():
        raise FileNotFoundError(f"decision log not found: {decisions_path}")
    decisions = load_decisions(decisions_path)
    transitions = load_transitions(transitions_path) if transitions_path.exists() else []

    instrument_id = params.bar_type.split("-", 1)[0]
    meta: dict[str, Any] = {
        "session_dir": str(session_dir),
        "streaming_dir": str(streaming_dir),
        "catalog_path": str(catalog_path),
    }

    research_catalog = ParquetDataCatalog(str(catalog_path))
    warmup_start_ns = _warmup_window_start_ns(decisions, params)
    # Catalog queries filter ts_init inclusively on both bounds, so the warmup
    # end is boundary - 1 to keep [warmup_start, boundary) exclusive.
    research_warmup = read_research_bars(
        research_catalog,
        params.bar_type,
        warmup_start_ns,
        _boundary_ns(decisions) - 1,
    )
    day_start_ns = _session_day_start_ns(decisions)
    day_end_ns = day_start_ns + 24 * 3600 * 1_000_000_000
    last_seen_ns = decisions[-1].ts_event_ns
    research_live = read_research_bars(research_catalog, params.bar_type, day_start_ns, min(day_end_ns, last_seen_ns + 1))

    streamed = read_streamed_objects(streaming_dir)
    streamed_bars, order_records, position_records = partition_streamed(
        streamed,
        params.bar_type,
        instrument_id,
    )
    results, check_meta = compute_checks(
        decisions,
        transitions,
        research_warmup,
        research_live,
        streamed_bars,
        order_records,
        position_records,
        params,
        portfolio,
    )
    meta.update(check_meta)
    return results, meta


def _session_start_ns(decisions: list[Decision]) -> int:
    return min(d.clock_ns for d in decisions)


def _boundary_ns(decisions: list[Decision]) -> int:
    """ts of the first non-warmup decision bar (the warmup/live split point)."""
    live_decisions = [d for d in decisions if d.action != "skip-warmup"]
    return live_decisions[0].ts_event_ns if live_decisions else decisions[-1].ts_event_ns


def _warmup_window_start_ns(decisions: list[Decision], params: AcceptanceParams) -> int:
    start_dt = warmup_start(
        datetime.fromtimestamp(_session_start_ns(decisions) / 1e9, tz=UTC),
        params.bar_type,
        params.warmup_bars,
        WARMUP_CALENDAR_MULTIPLE,
    )
    return int(start_dt.timestamp() * 1e9)


def _session_day_start_ns(decisions: list[Decision]) -> int:
    live_decisions = [d for d in decisions if d.action != "skip-warmup"]
    ref = live_decisions[-1] if live_decisions else decisions[-1]
    day = (
        datetime.fromtimestamp(ref.ts_event_ns / 1e9, tz=UTC)
        .astimezone(VN_TZ)
        .date()
    )
    midnight = datetime(day.year, day.month, day.day, tzinfo=VN_TZ)
    return int(midnight.astimezone(UTC).timestamp() * 1e9)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Post-session acceptance report (6 checks) for one paper session",
    )
    parser.add_argument("--session-dir", type=Path, help="session dir with decisions.jsonl")
    parser.add_argument("--streaming-dir", type=Path, help="streaming instance dir (feathers + config.json)")
    parser.add_argument("--catalog", type=Path, default=Path(DEFAULT_CATALOG_PATH), help="research ETL catalog")
    parser.add_argument("--bar-type", type=str, default=None, help="override the bar type")
    parser.add_argument("--output-dir", type=Path, default=None, help="report output dir (default: session dir)")
    args = parser.parse_args(argv)

    session_dir = args.session_dir if args.session_dir is not None else latest_session_dir(Path(DEFAULT_SESSIONS_DIR))
    session_dir = session_dir.resolve()
    if args.streaming_dir is not None:
        streaming_dir = resolve_streaming_dir(args.streaming_dir.resolve())
    else:
        streaming_dir = latest_streaming_instance(Path(DEFAULT_STREAMING_ROOT))
    catalog_path = args.catalog.resolve()

    manifest = load_manifest(streaming_dir, session_dir)
    params = resolve_params(manifest, bar_type=args.bar_type)
    portfolio = build_portfolio(manifest)

    results, meta = run_acceptance(
        session_dir,
        streaming_dir,
        catalog_path,
        params,
        portfolio,
    )
    output_dir = args.output_dir.resolve() if args.output_dir is not None else session_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    gated_failures = [r for r in results if r.gated and r.status == "FAIL"]
    exit_code = 1 if gated_failures else 0
    write_reports(output_dir, results, meta, exit_code)

    for result in results:
        print(f"{result.status:6s} {result.name}")
        if result.detail:
            print(f"       {result.detail}")
    print(f"exit code: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
