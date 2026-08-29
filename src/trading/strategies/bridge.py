"""Bridge strategy for the live wiring phase (workstream B of DEC-008).

One 1-minute bar in, one target out, at most one working order at a time.

Data path
---------
- ``on_start`` resolves the instrument from the cache (requesting it when
  missing, per the DEC-008 design the DNSE data adapter's
  ``DnseInstrumentProvider`` loads it), then subscribes to the configured
  ``BarType`` and requests historical bars for the warmup window.
- ``on_bar`` and ``on_historical_data`` both feed the same rolling buffers
  (``collections.deque`` per field, capped at ``buffer_bars``). Duplicate
  bars are dropped by ``ts_event`` so a historical response overlapping the
  live stream cannot double-count.
- No decision is taken until ``warmup_bars`` closes are collected.

Decision path (per bar, in this order)
--------------------------------------
1. Force-close check: local time (Asia/Ho_Chi_Minh) at/after
   ``force_close_local_time`` -> cancel all orders and close the position,
   then block the rest of the day (same-day re-entry blocked). The first bar
   of a new local day re-arms the session.
2. ``portfolio.compute_target(bars, ts)`` -> ``TargetPosition`` (contracts.py).
3. ``risk.gate(target)`` -> ``(allowed, reason)``; denied targets are logged
   and skipped.
4. Cooldown: skip when less than ``cooldown_secs`` elapsed since the last
   order submission.
5. Gap: skip when ``abs(target - current) < min_gap_contracts``.
6. No stacking: skip when a working (non-terminal) order exists for the
   instrument.

Order construction
------------------
The bridge consumes bars, not the book, so the reference price is the last
trade price = latest bar close (marketable side by construction):

- ``order_style="LO"`` (default): limit order at the last close with
  ``TimeInForce.DAY``. The entrade execution adapter maps ``LIMIT + DAY`` to
  broker order type ``LO``.
- ``order_style="MAK"``: market order with ``TimeInForce.IOC``. The entrade
  adapter maps ``MARKET + IOC`` to broker order type ``MAK``.

Position source (documented choice): the current position is read from the
Nautilus cache (``self.cache.positions(instrument_id=..., strategy_id=...)``),
not from ``self.portfolio``. ``self.portfolio`` is a ``PortfolioFacade`` with
no per-strategy position accessor (only ``net_position`` across accounts);
under the NETTING OMS used by the entrade adapter the cache holds the single
per-strategy position, so it is the authoritative source. The strategy never
imports ``trading.portfolio`` - it only calls the ``Portfolio`` protocol
duck-typed via ``BridgeConfig.portfolio``.

Client order IDs are deterministic: ``f"{prefix}-{timestamp_ns}"``.

All decision helpers are module-level pure functions taking plain values so
they are unit-testable without a running node (see
``src/trading/tests/test_bridge.py``).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time as local_time
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import TimeInForce
from nautilus_trader.model.events.order import OrderCanceled
from nautilus_trader.model.events.order import OrderDenied
from nautilus_trader.model.events.order import OrderExpired
from nautilus_trader.model.events.order import OrderFilled
from nautilus_trader.model.events.order import OrderRejected
from nautilus_trader.model.identifiers import ClientOrderId
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.trading.strategy import Strategy

from trading.contracts import TargetPosition
from trading.notify import format_force_close
from trading.notify import format_order_outcome
from trading.notify import format_session
from trading.notify import notify_or_log

#: Local timezone used for the session/force-close rules (VN derivative market).
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

#: entrade adapter mappings (src/trading/adapters/entrade/contracts.py):
#: LIMIT + DAY -> "LO"; MARKET + IOC -> "MAK".
LO_TIME_IN_FORCE = TimeInForce.DAY
MAK_TIME_IN_FORCE = TimeInForce.IOC

#: Calendar-time multiple applied on top of the raw bar count when computing
#: the warmup request window, because bars only exist inside VN trading hours
#: (a 1-minute bar needs roughly 3x calendar time to accumulate 800 bars).
WARMUP_CALENDAR_MULTIPLE = 2.0

#: Minutes per bar aggregation step (step x unit = bar period in minutes).
_AGGREGATION_MINUTES = {
    "MINUTE": 1,
    "HOUR": 60,
    "DAY": 1440,
    "WEEK": 10080,
}


# --------------------------------------------------------------------------- #
# Pure decision helpers (no Nautilus runtime objects; unit-testable standalone)
# --------------------------------------------------------------------------- #


def _parse_local_time(value: str) -> local_time:
    """Parse an ``HH:MM`` local time string, raising ``ValueError`` on garbage."""
    try:
        hour, minute = value.split(":", 1)
        return local_time(int(hour), int(minute))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(
            f"Invalid local time {value!r}, expected 'HH:MM' (e.g. '14:00')",
        ) from error


def should_force_close(ts: datetime, force_close_time_str: str, tz: ZoneInfo) -> bool:
    """Return whether ``ts`` is at/after the force-close time in ``tz``.

    Pure per-timestamp rule: the timestamp is converted to ``tz`` and its
    time-of-day is compared against ``force_close_time_str``. A timestamp on
    any day before the cutoff (including a new day's morning) returns False,
    which is what lets the strategy re-arm the session on day rollover.
    """
    if ts.tzinfo is None:
        raise ValueError("should_force_close requires a timezone-aware timestamp")
    cutoff = _parse_local_time(force_close_time_str)
    return ts.astimezone(tz).time() >= cutoff


def target_delta(target_contracts: int, current_contracts: int) -> int:
    """Signed contracts to trade to reach the target from the current position."""
    return int(target_contracts) - int(current_contracts)


def is_below_min_gap(delta: int, min_gap_contracts: int) -> bool:
    """True when the trade is below the minimum gap and should be skipped."""
    return abs(delta) < min_gap_contracts


def is_cooldown_elapsed(
    last_submission_ns: int | None,
    now_ns: int,
    cooldown_secs: float,
) -> bool:
    """True when enough time has passed since the last submission."""
    if last_submission_ns is None:
        return True
    return (now_ns - last_submission_ns) >= cooldown_secs * 1_000_000_000


def has_working_orders(open_order_count: int, inflight_order_count: int) -> bool:
    """True when any non-terminal order is open or in flight (no stacking)."""
    return (open_order_count or 0) + (inflight_order_count or 0) > 0


def client_order_id_for(prefix: str, ts_ns: int) -> str:
    """Deterministic client order ID value from a prefix and nanosecond timestamp."""
    return f"{prefix}-{ts_ns}"


def order_side_for_delta(delta: int) -> str:
    """Return ``'BUY'`` for positive delta, ``'SELL'`` for negative; raise on zero."""
    if delta > 0:
        return "BUY"
    if delta < 0:
        return "SELL"
    raise ValueError("target delta must be non-zero to build an order")


def bar_period_timedelta(bar_type_str: str) -> timedelta:
    """Minutes per bar parsed from a BarType string like ``VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL``."""
    parts = bar_type_str.split("-")
    if len(parts) < 3:
        raise ValueError(f"Invalid bar type string: {bar_type_str!r}")
    try:
        step = int(parts[1])
    except ValueError as error:
        raise ValueError(f"Invalid bar step in {bar_type_str!r}") from error
    aggregation = parts[2].upper()
    try:
        return timedelta(minutes=step * _AGGREGATION_MINUTES[aggregation])
    except KeyError as error:
        raise ValueError(f"Unsupported bar aggregation {aggregation!r}") from error


def warmup_start(
    now_utc: datetime,
    bar_type_str: str,
    warmup_bars: int,
    calendar_multiple: float = WARMUP_CALENDAR_MULTIPLE,
) -> datetime:
    """UTC start time for a historical request that yields ~``warmup_bars`` bars.

    ``calendar_multiple`` inflates the window for non-trading hours; the rolling
    buffer caps how much is actually retained.
    """
    if now_utc.tzinfo is None:
        raise ValueError("warmup_start requires a timezone-aware now_utc")
    return now_utc - bar_period_timedelta(bar_type_str) * warmup_bars * calendar_multiple


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass
class BridgeConfig:
    """Configuration for :class:`BridgeStrategy`.

    ``portfolio`` and ``risk`` are the workstream-A/workstream-C protocol
    implementations, passed by duck typing (never imported concretely).
    """

    instrument_id: str
    bar_type: str
    portfolio: Any  # implements trading.contracts.Portfolio
    risk: Any  # implements trading.contracts.RiskController
    order_style: str = "LO"  # "LO" | "MAK"
    cooldown_secs: float = 5.0
    min_gap_contracts: int = 1
    force_close_local_time: str = "14:00"
    warmup_bars: int = 800
    buffer_bars: int = 2000
    client_order_id_prefix: str = "bridge"
    #: Nautilus order_id_tag -> strategy id becomes "BridgeStrategy-<tag>"
    #: (v1 formula: f"{component_id}-{order_id_tag}"); the risk overlay's
    #: ``bridge_strategy_id`` must match this exactly.
    order_id_tag: str = "bridge"
    #: Duck-typed telegram notifier (notify(text) or None); alerting is
    #: best-effort and never blocks the decision loop.
    notifier: Any = None


# --------------------------------------------------------------------------- #
# Strategy
# --------------------------------------------------------------------------- #


class BridgeStrategy(Strategy):
    """Nautilus strategy bridging bars -> Portfolio target -> gated orders."""

    def __init__(self, config: BridgeConfig) -> None:
        if not isinstance(config, BridgeConfig):
            raise TypeError(f"config must be a BridgeConfig, got {type(config).__name__}")
        if config.order_style not in ("LO", "MAK"):
            raise ValueError(f"order_style must be 'LO' or 'MAK', got {config.order_style!r}")
        if config.warmup_bars < 1 or config.buffer_bars < 1:
            raise ValueError("warmup_bars and buffer_bars must be positive")
        if config.buffer_bars < config.warmup_bars:
            raise ValueError("buffer_bars must be >= warmup_bars so warmup can complete")
        _parse_local_time(config.force_close_local_time)  # validate eagerly

        self._instrument_id = InstrumentId.from_str(config.instrument_id)
        self._bar_type = BarType.from_str(config.bar_type)
        if self._bar_type.instrument_id != self._instrument_id:
            raise ValueError(
                "bar_type instrument "
                f"{self._bar_type.instrument_id} does not match instrument_id {self._instrument_id}",
            )

        super().__init__(config=StrategyConfig(order_id_tag=config.order_id_tag))
        # ``self.config`` is owned by the Nautilus Strategy base; keep ours apart.
        self.bridge_config = config
        self._notifier = config.notifier

        # Rolling bar buffers (per field, capped at buffer_bars).
        self._closes: deque[float] = deque(maxlen=config.buffer_bars)
        self._volumes: deque[float] = deque(maxlen=config.buffer_bars)
        self._bar_ts: deque[int] = deque(maxlen=config.buffer_bars)
        self._last_bar_ts_ns: int | None = None

        # Instrument/order machinery (populated on start).
        self._instrument: Instrument | None = None
        self._order_factory: OrderFactory | None = None
        self._instrument_ready = False
        self._bars_requested = False

        # Session state.
        self._session_closed = False
        self._session_date: date | None = None
        self._last_submit_ns: int | None = None
        self._pending_client_order_ids: set[ClientOrderId] = set()

        # Telemetry.
        self._orders_submitted = 0
        self._orders_filled = 0
        self._orders_rejected = 0
        self._orders_denied = 0

    # -- lifecycle ---------------------------------------------------------- #

    def on_start(self) -> None:
        """Resolve the instrument, build the order factory, subscribe and warm up."""
        notify_or_log(
            self._notifier,
            format_session(f"session starting | {self._instrument_id}"),
        )
        instrument = self.cache.instrument(self._instrument_id)
        if instrument is not None:
            self._on_instrument_ready(instrument)
        else:
            self.log.info(
                f"Bridge {self.id} requesting instrument {self._instrument_id}",
            )
            self.request_instrument(self._instrument_id)

    def on_instrument(self, instrument: Instrument) -> None:
        """Deferred instrument resolution when the instrument was not cached."""
        if self._instrument_ready or instrument.id != self._instrument_id:
            return
        self._on_instrument_ready(instrument)

    def _on_instrument_ready(self, instrument: Instrument) -> None:
        self._instrument = instrument
        self._order_factory = OrderFactory(
            trader_id=self.trader_id,
            strategy_id=self.id,
            clock=self.clock,
            cache=self.cache,
        )
        self._instrument_ready = True
        self.log.info(
            f"Bridge {self.id} instrument ready: {instrument.id} "
            f"(price_precision={instrument.price_precision}, "
            f"size_precision={instrument.size_precision})",
        )
        self.subscribe_bars(self._bar_type)
        self._request_warmup()

    def _request_warmup(self) -> None:
        if self._bars_requested:
            return
        self._bars_requested = True
        start = warmup_start(
            self.clock.utc_now(),
            self.bridge_config.bar_type,
            self.bridge_config.warmup_bars,
        )
        self.log.info(
            f"Bridge {self.id} requesting historical bars for warmup "
            f"since {start.isoformat()}",
        )
        self.request_bars(self._bar_type, start=start)

    # -- data handlers ------------------------------------------------------ #

    def on_bar(self, bar: Bar) -> None:
        """One decision per bar: session rules, target, risk gate, throttle, gap, no-stacking."""
        if bar.bar_type != self._bar_type:
            return
        self._append_bar(bar)

        now = self.clock.utc_now()
        self._update_session_date(now)

        if self._session_closed:
            return

        if should_force_close(now, self.bridge_config.force_close_local_time, VN_TZ):
            self._force_close(now)
            self._session_closed = True
            return

        if not self._warmed_up():
            return

        target = self.bridge_config.portfolio.compute_target(
            self._bars_snapshot(),
            now,
        )
        if not isinstance(target, TargetPosition):
            raise TypeError(
                f"portfolio.compute_target must return TargetPosition, got {type(target).__name__}",
            )

        allowed, reason = self.bridge_config.risk.gate(target)
        if not allowed:
            self.log.info(
                f"Bridge {self.id} target denied by risk controller: {reason} "
                f"(target={target.target_contracts})",
            )
            return

        current_contracts = self._current_position_contracts()
        delta = target_delta(target.target_contracts, current_contracts)

        now_ns = self.clock.timestamp_ns()
        if not is_cooldown_elapsed(
            self._last_submit_ns,
            now_ns,
            self.bridge_config.cooldown_secs,
        ):
            return

        if is_below_min_gap(delta, self.bridge_config.min_gap_contracts):
            return

        if self._working_order_exists():
            return

        self._submit_target_delta(delta, now_ns)

    def on_historical_data(self, data: Any) -> None:
        """Feed the warmup response into the same rolling buffers as live bars."""
        if data is None:
            return
        bars = [data] if isinstance(data, Bar) else list(data)
        appended = 0
        for item in bars:
            if isinstance(item, Bar) and item.bar_type == self._bar_type:
                self._append_bar(item)
                appended += 1
        if appended:
            self.log.info(
                f"Bridge {self.id} appended {appended} historical bars "
                f"(buffer={len(self._closes)}/{self.bridge_config.buffer_bars})",
            )

    # -- order event callbacks ---------------------------------------------- #

    def on_order_filled(self, event: OrderFilled) -> None:
        self._orders_filled += 1
        self._pending_client_order_ids.discard(event.client_order_id)
        self.log.info(
            f"Bridge {self.id} order filled: client_order_id={event.client_order_id} "
            f"instrument={event.instrument_id} side={event.order_side.name} "
            f"last_qty={event.last_qty} commission={event.commission}",
        )

    def on_order_rejected(self, event: OrderRejected) -> None:
        self._orders_rejected += 1
        self._pending_client_order_ids.discard(event.client_order_id)
        self.log.info(
            f"Bridge {self.id} order rejected: client_order_id={event.client_order_id} "
            f"reason={event.reason}",
        )
        notify_or_log(
            self._notifier,
            format_order_outcome("REJECTED", client_order_id=str(event.client_order_id), reason=event.reason),
        )

    def on_order_canceled(self, event: OrderCanceled) -> None:
        self._pending_client_order_ids.discard(event.client_order_id)
        self.log.info(
            f"Bridge {self.id} order canceled: client_order_id={event.client_order_id}",
        )

    def on_order_denied(self, event: OrderDenied) -> None:
        self._orders_denied += 1
        self._pending_client_order_ids.discard(event.client_order_id)
        self.log.info(
            f"Bridge {self.id} order denied: client_order_id={event.client_order_id} "
            f"reason={event.reason}",
        )
        notify_or_log(
            self._notifier,
            format_order_outcome("DENIED", client_order_id=str(event.client_order_id), reason=event.reason),
        )

    def on_order_expired(self, event: OrderExpired) -> None:
        # DAY-TIF limit orders expire at the end of the session; clear the
        # pending set so a stale entry cannot lock out later submissions.
        self._pending_client_order_ids.discard(event.client_order_id)
        self.log.info(
            f"Bridge {self.id} order expired: client_order_id={event.client_order_id}",
        )

    # -- internals ---------------------------------------------------------- #

    def _append_bar(self, bar: Bar) -> None:
        """Append a bar to the rolling buffers, dropping duplicates by ts_event."""
        if self._last_bar_ts_ns is not None and bar.ts_event <= self._last_bar_ts_ns:
            return
        self._last_bar_ts_ns = bar.ts_event
        self._closes.append(bar.close.as_double())
        self._volumes.append(bar.volume.as_double())
        self._bar_ts.append(bar.ts_event)

    def _bars_snapshot(self) -> dict[str, list[float]]:
        return {"close": list(self._closes), "volume": list(self._volumes)}

    def _warmed_up(self) -> bool:
        return len(self._closes) >= self.bridge_config.warmup_bars

    def _update_session_date(self, now: datetime) -> None:
        today = now.astimezone(VN_TZ).date()
        if self._session_date is None:
            self._session_date = today
            return
        if self._session_date != today:
            was_closed = self._session_closed
            self._session_date = today
            self._session_closed = False
            if was_closed:
                self.log.info(
                    f"Bridge {self.id} session re-armed for {today.isoformat()}",
                )

    def _force_close(self, now: datetime) -> None:
        """Cancel all orders and close the position (idempotent per session)."""
        self.log.info(
            f"Bridge {self.id} force-close at {now.isoformat()} "
            f"(local {now.astimezone(VN_TZ).isoformat()})",
        )
        notify_or_log(
            self._notifier,
            format_force_close(
                self._current_position_contracts(),
                time=now.astimezone(VN_TZ).strftime("%H:%M"),
            ),
        )
        self.cancel_all_orders(self._instrument_id)
        positions = self.cache.positions(
            instrument_id=self._instrument_id,
            strategy_id=self.id,
        )
        for position in positions:
            if position.is_closed:
                continue
            # IOC market order so the entrade adapter maps it to "MAK"
            # (MARKET+GTC is rejected by entrade_order_parameters).
            self.close_position(position, time_in_force=TimeInForce.IOC)

    def _current_position_contracts(self) -> int:
        """Signed current position in contracts, read from the Nautilus cache."""
        positions = self.cache.positions(
            instrument_id=self._instrument_id,
            strategy_id=self.id,
        )
        position = positions[0] if positions else None
        if position is None or position.is_closed:
            return 0
        quantity = int(position.quantity.as_double())
        return quantity if position.is_long else -quantity

    def _working_order_exists(self) -> bool:
        """True when any non-terminal order exists (open, inflight, or pending)."""
        open_count = len(
            self.cache.orders_open(
                instrument_id=self._instrument_id,
                strategy_id=self.id,
            ),
        )
        inflight_count = len(
            self.cache.orders_inflight(
                instrument_id=self._instrument_id,
                strategy_id=self.id,
            ),
        )
        return has_working_orders(open_count, inflight_count) or bool(
            self._pending_client_order_ids,
        )

    def _submit_target_delta(self, delta: int, ts_ns: int) -> None:
        if self._order_factory is None or self._instrument is None:
            self.log.warning(
                f"Bridge {self.id} cannot submit: instrument not ready",
            )
            return
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        quantity = self._instrument.make_qty(abs(delta))
        client_order_id = ClientOrderId(
            client_order_id_for(self.bridge_config.client_order_id_prefix, ts_ns),
        )

        if self.bridge_config.order_style == "MAK":
            order = self._order_factory.market(
                instrument_id=self._instrument_id,
                order_side=side,
                quantity=quantity,
                time_in_force=MAK_TIME_IN_FORCE,
                client_order_id=client_order_id,
            )
        else:  # "LO"
            last_price = self._closes[-1] if self._closes else None
            if last_price is None:
                self.log.warning(
                    f"Bridge {self.id} cannot build LO: no close price buffered",
                )
                return
            order = self._order_factory.limit(
                instrument_id=self._instrument_id,
                order_side=side,
                quantity=quantity,
                price=self._instrument.make_price(last_price),
                time_in_force=LO_TIME_IN_FORCE,
                client_order_id=client_order_id,
            )

        self._last_submit_ns = ts_ns
        self._pending_client_order_ids.add(client_order_id)
        self._orders_submitted += 1
        self.log.info(
            f"Bridge {self.id} submitting {order.order_type.name} {side.name} "
            f"qty={order.quantity} coid={client_order_id} "
            f"tif={order.time_in_force.name}",
        )
        self.submit_order(order)

    def telemetry(self) -> dict[str, Any]:
        """Submission/rejection counters for operational reporting."""
        return {
            "orders_submitted": self._orders_submitted,
            "orders_filled": self._orders_filled,
            "orders_rejected": self._orders_rejected,
            "orders_denied": self._orders_denied,
            "session_closed": self._session_closed,
            "buffer_size": len(self._closes),
        }
