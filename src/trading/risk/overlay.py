"""Risk overlay actor — thin Nautilus v1 integration over the pure ``RiskLedger``.
Driven by the same bar stream as the bridge, order fills, and a heartbeat timer.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events.order import OrderEvent, OrderFilled
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from core import RiskConfig, RiskDecision, RiskState, TargetPosition
from trading.notify import format_flatten_failed
from trading.notify import format_risk_state
from trading.notify import notify_or_log
from trading.risk.state import (
    ACTIVE,
    HALTED,
    REDUCING,
    REASON_EXPOSURE,
    REASON_LOSS,
    REASON_STALE,
    RiskLedger,
)

# --- transition JSONL helpers (observability only) ---------------------------
# Records every risk-state change (ACTIVE/HALTED/REDUCING + reason) as one
# JSONL line for the acceptance layer. Pure and failure-tolerant: a write
# error is logged, never raised, so logging can never affect trading behavior.

_LOGGER = logging.getLogger(__name__)
_ensured_dirs: set[str] = set()

START_STATE = "<start>"
REASON_STARTUP = "startup"


def format_transition(ts_ns: int, previous: str, current: str, reason: str | None) -> str:
    """Serialize one transition as a single JSONL line (no trailing newline)."""
    return json.dumps(
        {
            "ts_ns": ts_ns,
            "previous": previous,
            "current": current,
            "reason": reason,
        }
    )


def append_transition(path: str, line: str) -> None:
    """Append one JSONL line to ``path``, creating parent directories on the
    first write and flushing. Never raises on write errors: a failure logs a
    warning and returns (logging must never affect trading behavior)."""
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent not in _ensured_dirs:
            os.makedirs(parent, exist_ok=True)
            _ensured_dirs.add(parent)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
    except OSError as exc:
        _LOGGER.warning("RISK: transition log write failed for %s: %s", path, exc)


def transitions_since(
    new_status: str,
    new_reason: str,
    last_seen: tuple[str, str] | None,
) -> list[dict] | None:
    """One transition record when ``(new_status, new_reason)`` differs from the
    last-seen ``(status, reason)`` pair, else ``None`` (no change). The first
    observation (``last_seen is None``) anchors the sequence with
    ``previous="<start>"`` and ``reason="startup"``; later records carry the
    prior status and the new reason (``None`` when the reason is empty)."""
    if last_seen is not None and (new_status, new_reason) == last_seen:
        return None
    if last_seen is None:
        return [{"previous": START_STATE, "current": new_status, "reason": REASON_STARTUP}]
    return [
        {
            "previous": last_seen[0],
            "current": new_status,
            "reason": new_reason or None,
        }
    ]


# --- state save/load helpers (pure, unit-testable) ---------------------------


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dt_from_iso(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_overlay_state(ledger: RiskLedger, halted_latch: bool) -> dict[str, Any]:
    """Plain-values dict of the risk state machine for the Redis save/load hooks.

    Persists the status/reason (from ``decide()``), the halt latch, and the
    loss-limit bookkeeping (realized/marked PnL, position, entry, last mark,
    bar/session timestamps) so the trigger math is identical after restart.
    Datetimes are ISO strings (msgspec-safe).
    """
    return {
        "status": ledger.status,
        "reason": ledger.reason,
        "halted_latch": bool(halted_latch),
        "realized_pnl_vnd": float(ledger.realized_pnl_vnd),
        "marked_pnl_vnd": float(ledger.marked_pnl_vnd),
        "position": int(ledger.position),
        "avg_entry": ledger.avg_entry,
        "last_price": ledger.last_price,
        "last_bar_ts": _iso_or_none(ledger.last_bar_ts),
        "last_bar_seen_session": bool(ledger.last_bar_seen_session),
        "intraday_start_ts": _iso_or_none(ledger.intraday_start_ts),
    }


def apply_overlay_state(
    ledger: RiskLedger,
    state: dict[str, Any],
) -> tuple[str, str, bool]:
    """Restore risk bookkeeping from a saved state dict onto ``ledger``.

    Returns the effective ``(status, reason, halted_latch)``: a persisted
    HALTED status latches the halt so the actor stays halted after restart
    (the ledger's own ``decide()`` would otherwise recompute ACTIVE as soon
    as the trigger clears). Malformed/missing values fall back to ACTIVE
    defaults; never raises.
    """
    if not isinstance(state, dict):
        state = {}
    ledger.realized_pnl_vnd = _to_float(state.get("realized_pnl_vnd"), 0.0)
    ledger.marked_pnl_vnd = _to_float(state.get("marked_pnl_vnd"), 0.0)
    ledger.position = _to_int(state.get("position"), 0)
    avg = state.get("avg_entry")
    ledger.avg_entry = _to_float(avg, 0.0) if avg is not None else None
    last_px = state.get("last_price")
    ledger.last_price = _to_float(last_px, 0.0) if last_px is not None else None
    ledger.last_bar_ts = _dt_from_iso(state.get("last_bar_ts"))
    ledger.last_bar_seen_session = bool(state.get("last_bar_seen_session", False))
    ledger.intraday_start_ts = _dt_from_iso(state.get("intraday_start_ts"))

    status = state.get("status") or ACTIVE
    reason = state.get("reason") or ""
    if status not in (ACTIVE, HALTED, REDUCING):
        status, reason = ACTIVE, ""
    ledger.status = status
    ledger.reason = reason
    return status, reason, status == HALTED


def _dt_from_ns(ns: int) -> datetime:
    """Convert a Nautilus nanosecond timestamp to a tz-aware UTC datetime."""
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


class RiskOverlayActor(Strategy):
    """Component 7 overlay: bars/fills/heartbeat in, risk state and gates out.

    v1 API note: ``nautilus_trader.trading.actor.Actor`` does not exist in
    v1.231.0 (the base ``Actor`` lives at ``nautilus_trader.common.actor`` and
    lacks ``cancel_all_orders``/``close_position``/``close_all_positions``,
    which are ``Strategy`` methods), so the overlay is a strategy-side
    component. It implements the ``RiskController`` protocol
    (``decide``/``gate``/``status``) from ``core.contracts``.

    The risk thresholds (capital, loss limit, staleness, flatten retry,
    session close, instrument multiplier) come from the core ``RiskConfig``
    passed as ``risk_config``; the remaining kwargs are node wiring.

    Fill reception (verified against nautilus_trader v1.231.0): there is NO
    ``subscribe_order_events`` API in v1 — a strategy only receives order
    events for orders it submitted itself, routed on the per-strategy topic
    ``events.order.<strategy_id>``. The overlay subscribes to the bridge's
    topic through ``self.msgbus.subscribe`` in ``on_start`` (its own flatten
    fills arrive via ``on_order_event``); set ``bridge_strategy_id`` to the
    bridge's final strategy id (component name + ``-`` + order_id_tag, or
    the explicit ``strategy_id``).

    Alerting: log lines carry the stable prefix ``RISK:``; the
    flatten-failed alert logs at ERROR with an embedded ``CRITICAL`` token
    because v1's ``Logger`` has no critical level (levels are
    debug/info/warning/error).
    """

    def __init__(
        self,
        *,
        bar_type: BarType | str,
        risk_config: RiskConfig,
        order_id_tag: str = "risk",
        bridge_strategy_id: str | None = None,
        heartbeat_interval_secs: float = 1.0,
        transition_log_path: str | None = None,
        notifier: Any = None,
    ) -> None:
        if isinstance(risk_config, StrategyConfig) or not isinstance(risk_config, RiskConfig):
            raise TypeError(
                f"risk_config must be a core RiskConfig, got {type(risk_config).__name__}"
            )
        super().__init__(config=StrategyConfig(order_id_tag=order_id_tag))
        self._bar_type = (
            bar_type if isinstance(bar_type, BarType) else BarType.from_str(str(bar_type))
        )
        self._risk_config = risk_config
        self._notifier = notifier  # duck-typed: notify(text) or None
        self._ledger = RiskLedger(risk_config)
        self._last_state = RiskState(status=ACTIVE, reason="")
        self._flatten_attempts = 0
        self._flatten_active = False
        self._bridge_topic: str | None = None
        self._heartbeat_name = f"RISK_HEARTBEAT:{self.instrument_id}"
        self._flatten_name = f"RISK_FLATTEN:{self.instrument_id}"
        self._transition_log_path = transition_log_path
        self._heartbeat_interval_secs = heartbeat_interval_secs
        self._bridge_strategy_id = bridge_strategy_id
        self._last_seen: tuple[str, str] | None = None
        #: Set by on_load when a persisted HALTED status is restored; while
        #: latched, _evaluate keeps the actor HALTED no matter what the
        #: ledger's decide() would recompute (operator must intervene).
        self._halted_latch = False
        #: The persisted halt reason, kept stable while latched (decide() would
        #: otherwise clear the ledger reason when the trigger clears).
        self._halted_reason: str = ""

    @property
    def instrument_id(self):
        return self._bar_type.instrument_id

    @property
    def risk_config(self) -> RiskConfig:
        """The core risk configuration driving the ledger (trigger thresholds)."""
        return self._risk_config

    # -- lifecycle -----------------------------------------------------------

    def on_start(self) -> None:
        self._seed_position_from_cache()
        self.subscribe_bars(self._bar_type)
        if self._bridge_strategy_id:
            self._bridge_topic = f"events.order.{self._bridge_strategy_id}"
            self.msgbus.subscribe(topic=self._bridge_topic, handler=self._on_bridge_order_event)
            self.log.info(
                f"RISK: subscribing to bridge order events topic={self._bridge_topic}"
            )
        self.clock.set_timer(
            name=self._heartbeat_name,
            interval=timedelta(seconds=self._heartbeat_interval_secs),
            callback=self._on_heartbeat,
        )
        self._evaluate()
        self.log.info(
            f"RISK: overlay started instrument={self.instrument_id} "
            f"bar_type={self._bar_type}"
        )

    def on_stop(self) -> None:
        for name in (self._heartbeat_name, self._flatten_name):
            if name in self.clock.timer_names:
                self.clock.cancel_timer(name)
        if self._bridge_topic is not None:
            self.msgbus.unsubscribe(topic=self._bridge_topic, handler=self._on_bridge_order_event)
        self.log.info("RISK: overlay stopped")

    # -- data / event handlers ----------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        ts = _dt_from_ns(bar.ts_event)
        self._ledger.on_bar(ts)
        self._ledger.mark(bar.close.as_double(), ts)
        self._evaluate()

    def on_order_event(self, event: OrderEvent) -> None:
        # Own orders (the flatten market orders) also feed realized PnL.
        if isinstance(event, OrderFilled):
            self._handle_fill(event)

    def _on_bridge_order_event(self, event) -> None:
        if isinstance(event, OrderFilled) and event.instrument_id == self.instrument_id:
            self._handle_fill(event)

    def _handle_fill(self, event: OrderFilled) -> None:
        qty = int(event.last_qty.as_double())
        signed_qty = qty if event.order_side == OrderSide.BUY else -qty
        self._ledger.record_fill(
            event.last_px.as_double(),
            signed_qty,
            _dt_from_ns(event.ts_event),
        )
        self._evaluate()

    def _on_heartbeat(self, _event) -> None:
        # Dead-man's switch driver: re-mark with the last known price so
        # staleness (no fresh bar) is detectable even when the feed is silent.
        if self._ledger.last_price is not None:
            self._ledger.mark(self._ledger.last_price, datetime.now(timezone.utc))
        self._evaluate()

    # -- RiskController protocol (core.contracts) ----------------------------

    def decide(self, target: TargetPosition) -> RiskDecision:
        """Return the canonical risk decision for a portfolio target.

        The actual position is read from the Nautilus cache when available;
        this prevents a stale ledger position from becoming an order target.
        """
        if not isinstance(target, TargetPosition):
            raise TypeError("target must be a TargetPosition")
        self._evaluate()
        current = self._current_contracts()
        if self._halted_latch:
            return RiskDecision(
                target,
                0,
                "force-flat",
                self._halted_reason or "halted",
                current,
            )
        return self._ledger.decide_target(target, current)

    def gate(self, target: TargetPosition) -> tuple[bool, str]:
        """Compatibility gate derived from :meth:`decide`."""
        decision = self.decide(target)
        # The legacy boolean contract cannot carry a capped or force-flat
        # target. Only an unchanged approval is safe to expose as ``True``;
        # canonical callers consume ``decide`` and its approved target.
        return decision.action == "approve", decision.reason

    def status(self) -> RiskState:
        return RiskState(status=self._ledger.status, reason=self._ledger.reason)

    # -- state save/load hooks --------------------------------------------------
    # The kernel calls these via Trader.save()/load() -> Cache.update_strategy/
    # load_strategy -> database (Redis) when TradingNodeConfig.save_state/
    # load_state are set (verified in system/kernel.py + common/actor.pyx: the
    # hooks are ``on_save``/``on_load``, NOT ``on_save_state``/``on_load_state``).

    def on_save(self) -> dict[str, Any]:
        """Persist the risk state machine so an ACTIVE circuit breaker survives
        restart (the persisted HALTED status latches on load)."""
        return format_overlay_state(self._ledger, self._halted_latch)

    def on_load(self, state: dict[str, Any]) -> None:
        """Restore risk bookkeeping; a persisted HALTED status stays HALTED -
        the operator must intervene (no silent re-arm). Save/load errors are
        logged, never raised, so a corrupt state cannot break start-up."""
        try:
            status, reason, halted = apply_overlay_state(self._ledger, state)
            self._halted_latch = halted
            self._halted_reason = reason if halted else ""
            if halted:
                self.log.warning(
                    f"RISK: restored HALTED ({reason or 'unknown'}) from saved "
                    "state - trading stays halted; operator intervention required"
                )
            else:
                self.log.info(
                    f"RISK: restored risk state ({status}:{reason or 'ok'}) "
                    "from saved state"
                )
        except Exception as error:  # noqa: BLE001 - save/load must never break start
            self.log.warning(f"RISK: failed to load saved state: {error}")

    # -- transition logging (observability only) ------------------------------

    def _log_transition(self, status: str, reason: str) -> None:
        """Append one JSONL record per state change; a no-op without a path."""
        if self._transition_log_path is None:
            return
        records = transitions_since(status, reason, self._last_seen)
        if not records:
            return
        for record in records:
            append_transition(
                self._transition_log_path,
                format_transition(
                    time.time_ns(),
                    record["previous"],
                    record["current"],
                    record["reason"],
                ),
            )
        self._last_seen = (status, reason)

    # -- decision evaluation -------------------------------------------------

    def _evaluate(self) -> None:
        if self._halted_latch:
            # Restored HALTED circuit breaker: never silently re-arm. The
            # ledger's own decide() would recompute ACTIVE as soon as the
            # trigger clears (e.g. bars flowing again after a stale-feed
            # halt), so the latch pins the state until the operator
            # intervenes - including the ledger status the gate reads.
            self._ledger.status = HALTED
            self._ledger.reason = self._halted_reason
            state = RiskState(status=HALTED, reason=self._halted_reason)
            if state != self._last_state:
                self.log.warning(
                    f"RISK: still HALTED ({self._halted_reason or 'unknown'}) - "
                    "operator intervention required"
                )
                self._last_state = state
            return
        state = self._ledger.decide()
        self._log_transition(state.status, state.reason)
        if state != self._last_state:
            self.log.warning(
                f"RISK: state {self._last_state.status}:{self._last_state.reason or 'ok'} "
                f"-> {state.status}:{state.reason or 'ok'}"
            )
            notify_or_log(
                self._notifier,
                format_risk_state(
                    self._last_state.status,
                    state.status,
                    state.reason or "ok",
                ),
            )
            if state.status == HALTED and state.reason in (REASON_LOSS, REASON_STALE):
                self._start_flatten()
            elif state.status == REDUCING and state.reason == REASON_EXPOSURE:
                self.log.warning(
                    f"RISK: exposure cap exceeded - position {self._ledger.position} "
                    f"contracts vs max {self._risk_config.limits.max_contracts}; "
                    "only reducing moves will pass the gate"
                )
        self._last_state = state

    # -- flatten circuit breaker ---------------------------------------------

    def _start_flatten(self) -> None:
        """Arm the flatten circuit breaker: cancel-all + close-all with retry.

        Fires on a TRANSITION to HALTED caused by a loss or staleness
        trigger. Exposure-cap REDUCING is enforced passively through the
        gate (only position-reducing moves are allowed) and does not
        auto-flatten.
        """
        if self._flatten_active:
            return
        self._flatten_active = True
        self._flatten_attempts = 0
        self.clock.set_timer(
            name=self._flatten_name,
            interval=timedelta(seconds=self._risk_config.flatten_retry_secs),
            callback=self._on_flatten_timer,
        )
        self.log.warning(
            f"RISK: flatten circuit breaker armed "
            f"(max_attempts={self._risk_config.flatten_max_attempts}, "
            f"retry_secs={self._risk_config.flatten_retry_secs})"
        )
        self._on_flatten_timer(None)  # first attempt immediately

    def _on_flatten_timer(self, _event) -> None:
        if self._is_flat():
            self.log.warning(f"RISK: flatten complete - flat for {self.instrument_id}")
            notify_or_log(self._notifier, "\U00002705 TRADING | FLATTEN COMPLETE | flat")
            self._stop_flatten_timer()
            return
        self._flatten_attempts += 1
        if self._flatten_attempts > self._risk_config.flatten_max_attempts:
            self.log.error(
                f"RISK:CRITICAL flatten failed after "
                f"{self._risk_config.flatten_max_attempts} attempts - position "
                f"NOT flat for {self.instrument_id}; manual intervention required"
            )
            notify_or_log(
                self._notifier,
                format_flatten_failed(
                    str(self.instrument_id), self._risk_config.flatten_max_attempts
                ),
            )
            self._stop_flatten_timer()
            return
        self.log.warning(
            f"RISK: flatten attempt {self._flatten_attempts}/"
            f"{self._risk_config.flatten_max_attempts} - cancel_all + close_all "
            f"for {self.instrument_id}"
        )
        self.cancel_all_orders(self.instrument_id)
        self.close_all_positions(self.instrument_id)

    def _stop_flatten_timer(self) -> None:
        self._flatten_active = False
        if self._flatten_name in self.clock.timer_names:
            self.clock.cancel_timer(self._flatten_name)

    # -- cache / position helpers -------------------------------------------

    def _is_flat(self) -> bool:
        if self.cache is None:  # not registered (standalone construction/tests)
            return self._ledger.position == 0
        return not self.cache.positions_open(instrument_id=self.instrument_id)

    def _current_contracts(self) -> int:
        if self.cache is None:  # not registered (standalone construction/tests)
            return self._ledger.position
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        if positions:
            return int(sum(pos.signed_qty for pos in positions))
        return self._ledger.position

    def _seed_position_from_cache(self) -> None:
        """Restore the ledger position from the cache at start-up (the node
        config uses ``snapshot_positions=True``, so a restored position must
        be respected by the exposure cap from the first bar on)."""
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        if not positions:
            return
        net = int(sum(pos.signed_qty for pos in positions))
        avg = (
            sum(pos.avg_px_open * pos.signed_qty for pos in positions) / net if net != 0 else None
        )
        self._ledger.reconcile_position(net, avg)
        self.log.info(
            f"RISK: seeded ledger position {net} contracts (avg entry {avg}) from cache"
        )
