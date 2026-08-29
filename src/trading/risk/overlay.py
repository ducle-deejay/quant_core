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
  ``risk.gate(target)`` before every order and reads ``risk.status()``
  (``RiskController`` protocol in ``trading.contracts``).
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
- The flatten circuit breaker (cancel-all + close-all with retry) fires on a
  TRANSITION to HALTED caused by a loss or staleness trigger, matching the
  task contract. Exposure-cap REDUCING is enforced passively through the gate
  (only position-reducing moves are allowed) and does not auto-flatten.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import msgspec

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events.order import OrderEvent, OrderFilled
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from trading.contracts import RiskState, TargetPosition
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

    def gate(self, target: TargetPosition) -> tuple[bool, str]:
        """Gate one bridge target; re-evaluates risk first so the gate sees
        the freshest state (a fresh halt also arms the flatten breaker)."""
        self._evaluate()
        current = self._current_contracts()
        return self._ledger.gate(target.target_contracts, current)

    def status(self) -> RiskState:
        return RiskState(status=self._ledger.status, reason=self._ledger.reason)

    # -- decision evaluation -------------------------------------------------

    def _evaluate(self) -> None:
        state = self._ledger.decide()
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
