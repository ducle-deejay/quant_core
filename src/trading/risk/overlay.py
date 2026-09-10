"""Component 7 risk overlay actor - thin Nautilus v1 integration.

Wraps the pure ``RiskLedger`` (``trading.risk.state``) in a v1 ``Strategy``
subclass so the overlay can live inside the milestone-1 TradingNode and use the
v1 order-management helpers. It drives the ledger from the same 1-minute bar
stream as the bridge strategy, from order fills, and from a heartbeat timer
(dead-man's switch), and it executes the flatten circuit breaker with retry.

Integration notes (milestone 1, decision DEC-008):

- The overlay and the bridge strategy run in the SAME TradingNode for
  milestone 1. The canon (STG-7-RISK-OVERLAY 5.1) requires a separate process
  for the risk layer; process separation is a recorded accepted gap (DEC-008)
  for the live phase. The overlay is a separate component object with its own
  strategy id, so a strategy crash does not take it down, but a node crash
  still does.
- Register the overlay as an additional entry in ``TradingNodeConfig.strategies``
  via ``ImportableStrategyConfig`` (strategy_path ``trading.risk.overlay:
  RiskOverlayActor``, config_path ``trading.risk.overlay:RiskOverlayConfig``),
  using the same ``bar_type`` as the bridge. The bridge calls
  ``risk.decide(target)`` before every order and only pursues the returned
  approved target (``RiskController`` protocol in ``trading.contracts``).
- Fill reception (confirmed against v1.231.0): there is NO
  ``subscribe_order_events`` API in v1. A strategy only receives order events
  for orders it submitted itself, routed on the per-strategy topic
  ``events.order.<strategy_id>`` (registered in ``Strategy.register_base``).
  The overlay therefore subscribes to the bridge's topic through
  ``self.msgbus.subscribe`` - the exact mechanism Nautilus itself uses - and
  additionally receives its own flatten-order fills via ``on_order_event``.
  Set ``bridge_strategy_id`` in the config to the bridge's final strategy id
  (component name + ``-`` + order_id_tag, or the explicit ``strategy_id``).
  The cache-query alternative (reconcile position deltas per bar) is available
  but loses fill prices, so it is not used.
- Alerting: structured log lines carry the stable prefix ``RISK:``; the
  "still not flat" alert uses level ERROR because v1's ``Logger`` has no
  ``critical`` level (confirmed: levels are debug/info/warning/error) - the
  message embeds ``CRITICAL`` so the severity survives grepping.
- Transition log: with ``transition_log_path`` set, every risk-state change
  (status + reason) is appended as one JSONL record
  ``{"ts_ns", "previous", "current", "reason"}``, anchored by a
  ``previous="<start>"``/``reason="startup"`` record at start-up, for the
  acceptance layer to match against the trigger matrix. Observability only:
  write failures are logged via stdlib ``logging``, never raised.
- The flatten circuit breaker (cancel-all + close-all with retry) fires on a
  TRANSITION to HALTED caused by a loss or staleness trigger, matching the
  task contract. Exposure-cap REDUCING is enforced passively through the gate
  (only position-reducing moves are allowed) and does not auto-flatten.
- State persistence: ``on_save``/``on_load`` persist the risk state machine
  (status, reason, halt latch, loss-limit bookkeeping) through the kernel's
  save/load hooks (TradingNodeConfig ``save_state``/``load_state``). A
  restored HALTED status stays latched HALTED - the operator must intervene;
  the ledger's own day rollover / decide() cannot silently re-arm it.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import msgspec

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events.order import OrderEvent, OrderFilled
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from trading.contracts import RiskDecision, RiskState, TargetPosition
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
    RiskConfig,
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


class RiskOverlayConfig(StrategyConfig, kw_only=True, frozen=True):
    """Configuration for the risk overlay actor (v1 StrategyConfig subclass).

    ``bar_type`` must match the bridge strategy's bar subscription (the DNSE
    1-minute external bar type built by ``trading.adapters.dnse.data``).
    ``bridge_strategy_id`` names the bridge strategy whose order events the
    overlay consumes for fills; leave ``None`` to disable fill ingestion
    (position then only tracks the overlay's own flatten orders).

    v1.231.0 quirk: msgspec decodes a configured ``strategy_id`` into a
    ``StrategyId`` object, which ``Strategy.__init__`` then passes to
    ``Logger(name=...)`` (a plain ``str`` is required) and crashes. The actor
    normalizes the decoded id back to ``str`` before the base constructor, so
    setting ``strategy_id`` is tolerated; the final strategy id is always
    ``f"<component_id>-{order_id_tag}"``, so prefer setting ``order_id_tag``
    and letting ``component_id`` default to the class name. ``bridge_strategy_id``
    must match the bridge's final id computed the same way.
    ``transition_log_path`` (default ``None``) enables the observability-only
    per-transition JSONL log; ``None`` disables it.
    """

    bar_type: BarType
    bridge_strategy_id: str | None = None
    capital_vnd: float = 100_000_000.0
    max_contracts: int = 10
    intraday_loss_pct: float = 0.02
    staleness_secs: float = 60.0
    session_close_local_time: str = "14:00"
    tz: str = "Asia/Ho_Chi_Minh"
    flatten_max_attempts: int = 3
    flatten_retry_secs: float = 1.0
    contract_multiplier: float = 100_000.0
    heartbeat_interval_secs: float = 1.0
    transition_log_path: str | None = None

    def risk_config(self) -> RiskConfig:
        """Project the flat overlay fields onto the pure core config."""
        return RiskConfig(
            capital_vnd=self.capital_vnd,
            max_contracts=self.max_contracts,
            intraday_loss_pct=self.intraday_loss_pct,
            staleness_secs=self.staleness_secs,
            session_close_local_time=self.session_close_local_time,
            tz=self.tz,
            flatten_max_attempts=self.flatten_max_attempts,
            flatten_retry_secs=self.flatten_retry_secs,
            contract_multiplier=self.contract_multiplier,
        )


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
    (``gate``/``status``) from ``trading.contracts``.
    """

    def __init__(self, config: RiskOverlayConfig, *, notifier: Any = None) -> None:
        if config.strategy_id is not None and not isinstance(config.strategy_id, str):
            # v1.231.0: msgspec decodes strategy_id into a StrategyId; the base
            # constructor passes it to Logger(name=...) which needs a str.
            config = msgspec.structs.replace(config, strategy_id=str(config.strategy_id))
        super().__init__(config=config)
        self._notifier = notifier  # duck-typed: notify(text) or None
        self._ledger = RiskLedger(self.config.risk_config())
        self._last_state = RiskState(status=ACTIVE, reason="")
        self._flatten_attempts = 0
        self._flatten_active = False
        self._bridge_topic: str | None = None
        self._heartbeat_name = f"RISK_HEARTBEAT:{self.instrument_id}"
        self._flatten_name = f"RISK_FLATTEN:{self.instrument_id}"
        self._transition_log_path = config.transition_log_path
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
        return self.config.bar_type.instrument_id

    # -- lifecycle -----------------------------------------------------------

    def on_start(self) -> None:
        self._seed_position_from_cache()
        self.subscribe_bars(self.config.bar_type)
        if self.config.bridge_strategy_id:
            self._bridge_topic = f"events.order.{self.config.bridge_strategy_id}"
            self.msgbus.subscribe(topic=self._bridge_topic, handler=self._on_bridge_order_event)
            self.log.info(
                f"RISK: subscribing to bridge order events topic={self._bridge_topic}"
            )
        self.clock.set_timer(
            name=self._heartbeat_name,
            interval=timedelta(seconds=self.config.heartbeat_interval_secs),
            callback=self._on_heartbeat,
        )
        self._evaluate()
        self.log.info(
            f"RISK: overlay started instrument={self.instrument_id} "
            f"bar_type={self.config.bar_type}"
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

    # -- RiskController protocol (trading.contracts) -------------------------

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
                    f"contracts vs max {self.config.max_contracts}; only reducing "
                    "moves will pass the gate"
                )
        self._last_state = state

    # -- flatten circuit breaker ---------------------------------------------

    def _start_flatten(self) -> None:
        if self._flatten_active:
            return
        self._flatten_active = True
        self._flatten_attempts = 0
        self.clock.set_timer(
            name=self._flatten_name,
            interval=timedelta(seconds=self.config.flatten_retry_secs),
            callback=self._on_flatten_timer,
        )
        self.log.warning(
            f"RISK: flatten circuit breaker armed "
            f"(max_attempts={self.config.flatten_max_attempts}, "
            f"retry_secs={self.config.flatten_retry_secs})"
        )
        self._on_flatten_timer(None)  # first attempt immediately

    def _on_flatten_timer(self, _event) -> None:
        if self._is_flat():
            self.log.warning(f"RISK: flatten complete - flat for {self.instrument_id}")
            notify_or_log(self._notifier, f"\U00002705 TRADING | FLATTEN COMPLETE | flat")
            self._stop_flatten_timer()
            return
        self._flatten_attempts += 1
        if self._flatten_attempts > self.config.flatten_max_attempts:
            self.log.error(
                f"RISK:CRITICAL flatten failed after {self.config.flatten_max_attempts} "
                f"attempts - position NOT flat for {self.instrument_id}; "
                "manual intervention required"
            )
            notify_or_log(
                self._notifier,
                format_flatten_failed(str(self.instrument_id), self.config.flatten_max_attempts),
            )
            self._stop_flatten_timer()
            return
        self.log.warning(
            f"RISK: flatten attempt {self._flatten_attempts}/"
            f"{self.config.flatten_max_attempts} - cancel_all + close_all "
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
