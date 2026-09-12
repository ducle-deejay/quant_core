"""Target-position strategy: one 1-minute bar in, one portfolio target out,
one working order at a time. Consumes bars (never the book)."""

from __future__ import annotations

import json
import os
from collections import deque
from datetime import date
from datetime import datetime
from datetime import time as local_time
from datetime import timedelta
from datetime import timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
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

from core import Portfolio
from core import TargetPosition
from core.expiry import ExpiryState
from core.expiry import apply_expiry_gate

#: Local timezone used for the session/expiry rules (VN derivative market).
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

#: entrade adapter mappings (src/trading/adapters/entrade/contracts.py):
#: LIMIT + DAY -> "LO"; MARKET + IOC -> "MAK".
LO_TIME_IN_FORCE = TimeInForce.DAY
MAK_TIME_IN_FORCE = TimeInForce.IOC

#: Calendar-time multiple for the warmup request window. One-minute bars only
#: exist inside VN trading hours: with 241 bars/session and 5 sessions/week,
#: 7200 bars need ~30 sessions ~= 42 calendar days, i.e. a multiple of ~8.4x;
#: 10.0 adds margin for holidays and partial sessions. The rolling buffer caps
#: how much is actually retained.
WARMUP_CALENDAR_MULTIPLE = 10.0

#: Nautilus order_id_tag for every instance of this strategy; the final
#: strategy id is ``f"{type name}-{order_id_tag}"`` (v1 formula), i.e.
#: "TargetPositionStrategy-target". Node wiring (the safety monitor's
#: ``bridge_strategy_id``) must match this exact string.
ORDER_ID_TAG = "target"

#: Deterministic client-order-id prefix (``<prefix>-<timestamp_ns>``).
CLIENT_ORDER_ID_PREFIX = "target"

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


def in_session_window(
    now: datetime,
    windows: list[tuple[str, str]] | tuple[tuple[str, str], ...],
    tz: ZoneInfo,
) -> bool:
    """True when ``now``'s local time in ``tz`` falls inside a window.

    Windows are ``HH:MM`` ``(start, end)`` pairs, half-open ``[start, end)``:
    a timestamp exactly on a start boundary is inside, exactly on an end
    boundary is outside.
    """
    if now.tzinfo is None:
        raise ValueError("in_session_window requires a timezone-aware timestamp")
    now_time = now.astimezone(tz).time()
    for start_str, end_str in windows:
        start = _parse_local_time(start_str)
        end = _parse_local_time(end_str)
        if start <= now_time < end:
            return True
    return False


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


def format_decision(
    ts_event_ns: int,
    clock_ns: int,
    close: float | None,
    target: int | None,
    current_contracts: int,
    action: str,
    reason: str | None,
) -> str:
    """One JSON line for the per-bar decision log (pure, unit-testable).

    ``close``/``target``/``reason`` are null when not computed for that path
    (e.g. ``skip-warmup`` fires before ``compute_target``).
    """
    return json.dumps(
        {
            "ts_event_ns": int(ts_event_ns),
            "clock_ns": int(clock_ns),
            "close": close,
            "target": target,
            "current_contracts": int(current_contracts),
            "action": action,
            "reason": reason,
        },
    )


# -- session/expiry save/load helpers (pure, unit-testable) ------------------ #


def vn_today_iso(now_utc: datetime | None = None) -> str:
    """The Asia/Ho_Chi_Minh calendar date of ``now_utc`` as ``YYYY-MM-DD``.

    ``now_utc`` defaults to the wall-clock UTC now; a naive input is assumed
    UTC. Used by the save/load hooks to decide whether a persisted session
    belongs to the current trading day.
    """
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(VN_TZ).date().isoformat()


def format_target_state(
    session_date: date | None,
    session_closed: bool,
    last_submit_ns: int | None,
    expiry_state: ExpiryState | None = None,
) -> dict[str, Any]:
    """The strategy's persisted session/expiry-state dict (plain values, Redis-safe).

    ``session_date`` is ``None`` when no bar has been seen yet (fresh start).
    The ``ExpiryState`` dates are serialized as ISO strings (``None`` when
    unset), so the expiry gate survives a restart without re-forcing.
    """
    expiry = expiry_state if expiry_state is not None else ExpiryState()
    return {
        "session_date": session_date.isoformat() if session_date is not None else None,
        "session_closed": bool(session_closed),
        "last_submit_ns": last_submit_ns,
        "expiry_blocked_session_date": (
            expiry.blocked_session_date.isoformat()
            if expiry.blocked_session_date is not None
            else None
        ),
        "expiry_last_processed_expiry_date": (
            expiry.last_processed_expiry_date.isoformat()
            if expiry.last_processed_expiry_date is not None
            else None
        ),
    }


def expiry_state_from_saved(
    blocked_session_date: str | None,
    last_processed_expiry_date: str | None,
) -> ExpiryState:
    """Rebuild an ``ExpiryState`` from the ISO date strings in a saved state.

    Malformed values are treated as unset (the gate's own date logic clears
    stale entries); never raises on garbage input.
    """
    blocked = _date_from_iso_or_none(blocked_session_date)
    processed = _date_from_iso_or_none(last_processed_expiry_date)
    return ExpiryState(
        blocked_session_date=blocked,
        last_processed_expiry_date=processed,
    )


def _date_from_iso_or_none(value: Any) -> date | None:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def should_restore_session(saved_session_date: str | None, today_iso: str) -> bool:
    """True when a persisted session belongs to the same VN day as ``today_iso``.

    A new day must start fresh (the expiry/session machinery re-arms on
    day rollover anyway), so only a same-day restart restores the flags.
    """
    return saved_session_date is not None and saved_session_date == today_iso


def append_decision(path: str, line_dict: str | dict[str, Any]) -> bool:
    """Append one JSON line to ``path``, creating parent dirs on first write.

    ``line_dict`` may be a JSON string (e.g. from :func:`format_decision`) or
    a dict, which is serialized here. Best-effort writer: never raises;
    returns False on any OSError so a bad log path cannot crash the decision
    loop (the strategy logs the warning).
    """
    line = line_dict if isinstance(line_dict, str) else json.dumps(line_dict)
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


class TargetPositionConfig(StrategyConfig, frozen=True, kw_only=True):
    """Configuration for :class:`TargetPositionStrategy`.

    The portfolio is NOT part of the config: the strategy receives the
    ``Portfolio`` instance at construction (wired by ``build_node`` or the
    execution backtest injection), so no config path round-trip is needed.
    """

    instrument_id: str
    bar_type: str
    #: ``"LO"`` (limit at the last close, TimeInForce.DAY) or ``"MAK"``
    #: (market, TimeInForce.IOC); entrade adapter mapping.
    order_style: str = "LO"
    cooldown_secs: float = 5.0
    min_gap_contracts: int = 1
    #: VN local windows within which NEW orders may be submitted; the
    #: expiry force-flat branch runs before the window check and is unaffected.
    session_windows: tuple[tuple[str, str], ...] = (
        ("09:00", "11:30"),
        ("13:00", "14:30"),
    )
    warmup_bars: int
    buffer_bars: int = 2000
    #: Master switch for the expiry gate; False disables expiry handling.
    expiry_enabled: bool = True
    #: VN local cutoff on the front-month expiry day: at/after this time the
    #: gate force-flats; before it only reduce-only targets pass.
    expiry_close_time_local: str = "14:00"
    #: JSONL path for the per-bar decision log; None disables logging.
    decision_log_path: str | None = None


# --------------------------------------------------------------------------- #
# Strategy
# --------------------------------------------------------------------------- #


class TargetPositionStrategy(Strategy):
    """Nautilus strategy bridging bars -> Portfolio target -> gated orders.

    Order enforcement is NOT done here: denials arrive as ``OrderDenied``
    events from the Nautilus ``RiskEngine`` (trading state set by the safety
    monitor) and are written to the decision log with the reason preserved.
    """

    def __init__(self, config: TargetPositionConfig, portfolio: Portfolio) -> None:
        if not isinstance(config, TargetPositionConfig):
            raise TypeError(
                f"config must be a TargetPositionConfig, got {type(config).__name__}",
            )
        if config.order_style not in ("LO", "MAK"):
            raise ValueError(f"order_style must be 'LO' or 'MAK', got {config.order_style!r}")
        if config.warmup_bars < 1 or config.buffer_bars < 1:
            raise ValueError("warmup_bars and buffer_bars must be positive")
        if config.buffer_bars < config.warmup_bars:
            raise ValueError("buffer_bars must be >= warmup_bars so warmup can complete")
        _parse_local_time(config.expiry_close_time_local)  # validate eagerly
        if not config.session_windows:
            raise ValueError("session_windows must not be empty")
        for window in config.session_windows:
            try:
                start_str, end_str = window
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"session_windows entries must be (start, end) HH:MM pairs, got {window!r}",
                ) from error
            _parse_local_time(start_str)
            _parse_local_time(end_str)

        self._instrument_id = InstrumentId.from_str(config.instrument_id)
        self._bar_type = BarType.from_str(config.bar_type)
        if self._bar_type.instrument_id != self._instrument_id:
            raise ValueError(
                "bar_type instrument "
                f"{self._bar_type.instrument_id} does not match instrument_id {self._instrument_id}",
            )

        super().__init__(
            config=StrategyConfig(order_id_tag=ORDER_ID_TAG),
        )
        # ``self.config`` is owned by the Nautilus Strategy base (and
        # ``self.portfolio`` by the Actor base); keep ours apart.
        self.strategy_config = config
        self._portfolio = portfolio

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

        # Session + expiry gate state (persisted via on_save/on_load).
        self._session_closed = False
        self._session_date: date | None = None
        self._last_submit_ns: int | None = None
        self._expiry_state = ExpiryState()
        self._pending_client_order_ids: set[ClientOrderId] = set()

        # Telemetry.
        self._orders_submitted = 0
        self._orders_filled = 0
        self._orders_rejected = 0
        self._orders_denied = 0

    # -- lifecycle ---------------------------------------------------------- #

    def on_start(self) -> None:
        """Resolve the instrument, build the order factory, subscribe and warm up."""
        self.log.info(f"TargetPosition {self.id} session starting | {self._instrument_id}")
        instrument = self.cache.instrument(self._instrument_id)
        if instrument is not None:
            self._on_instrument_ready(instrument)
        else:
            self.log.info(
                f"TargetPosition {self.id} requesting instrument {self._instrument_id}",
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
            f"TargetPosition {self.id} instrument ready: {instrument.id} "
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
            self.strategy_config.bar_type,
            self.strategy_config.warmup_bars,
        )
        self.log.info(
            f"TargetPosition {self.id} requesting historical bars for warmup "
            f"since {start.isoformat()}",
        )
        self.request_bars(self._bar_type, start=start)

    # -- data handlers ------------------------------------------------------ #

    def on_bar(self, bar: Bar) -> None:
        """One decision per bar; every exit path appends a decision-log line.

        Decision path, in this exact order:

        1. Expiry gate (early call with target 0; state persisted in
           ``_expiry_state``): on the VN30 front-month expiry day at/after
           ``expiry_close_time_local`` (Asia/Ho_Chi_Minh) the gate
           force-flats (cancel + close) and blocks re-entry for the rest of
           the session. This branch runs BEFORE the warmup and session-window
           checks so the expiry close fires even while warming up.
        2. Warmup: no decision until ``warmup_bars`` closes are collected.
        3. Session window: new orders only inside ``session_windows``.
        4. ``portfolio.compute_target(bars, ts)`` -> ``TargetPosition``.
        5. Expiry reduce-only clamp: BEFORE the cutoff on an expiry day the
           portfolio target is replaced by the gate's
           ``approved_target_contracts`` (no entry/increase may run on an
           expiry day before the close); the gate reason propagates to the
           decision log.
        6. Cooldown: skip when less than ``cooldown_secs`` elapsed since
           the last order submission.
        7. Gap: skip when ``abs(target - current) < min_gap_contracts``.
        8. No stacking: skip when a working (non-terminal) order exists
           for the instrument, then submit.

        RiskEngine denials do not appear here: they arrive asynchronously
        as ``OrderDenied`` events (see :meth:`on_order_denied`).
        """
        if bar.bar_type != self._bar_type:
            return
        self._append_bar(bar)

        now = self.clock.utc_now()
        now_ns = self.clock.timestamp_ns()
        self._update_session_date(now)

        if self._session_closed:
            self._log_decision(bar, now_ns, "skip-session-closed")
            return

        # Step 1: expiry gate. The candidate target is not known yet (scoring
        # has not run), so the early call carries 0 and only the force-flat /
        # re-entry branches act here; the reduce-only clamp re-runs the gate
        # with the real target after scoring (step 5). The gate consumes a
        # pandas UTC timestamp; the Nautilus clock datetime is converted here.
        gate_ts = pd.Timestamp(now)
        gate = apply_expiry_gate(
            gate_ts,
            target_contracts=0,
            current_contracts=self._current_position_contracts(),
            state=self._expiry_state,
            enabled=self.strategy_config.expiry_enabled,
            close_time_local=self.strategy_config.expiry_close_time_local,
            tz=str(VN_TZ),
        )
        self._expiry_state = gate.state
        if gate.force_flat:
            self._force_close(now)
            self._session_closed = True
            self._log_decision(bar, now_ns, "force-close", reason=gate.reason)
            return
        if gate.reentry_blocked:
            self._session_closed = True
            self._log_decision(
                bar, now_ns, "skip-session-closed", reason=gate.reason
            )
            return

        if not self._warmed_up():
            self._log_decision(bar, now_ns, "skip-warmup")
            return

        if not in_session_window(now, self.strategy_config.session_windows, VN_TZ):
            self._log_decision(bar, now_ns, "skip-window")
            return

        target = self._portfolio.compute_target(
            self._bars_snapshot(),
            now,
        )
        if not isinstance(target, TargetPosition):
            raise TypeError(
                f"portfolio.compute_target must return TargetPosition, got {type(target).__name__}",
            )

        # Step 5: clamp the portfolio target through the expiry gate's
        # reduce-only result (before the cutoff on an expiry day). The
        # approved target replaces the portfolio target and the gate reason
        # propagates to every subsequent decision-log line.
        current_contracts = self._current_position_contracts()
        clamp = apply_expiry_gate(
            gate_ts,
            target_contracts=target.target_contracts,
            current_contracts=current_contracts,
            state=self._expiry_state,
            enabled=self.strategy_config.expiry_enabled,
            close_time_local=self.strategy_config.expiry_close_time_local,
            tz=str(VN_TZ),
        )
        self._expiry_state = clamp.state
        approved_target = clamp.approved_target_contracts
        expiry_reason: str | None = clamp.reason or None
        delta = target_delta(approved_target, current_contracts)

        if expiry_reason is not None and delta == 0:
            # No reducing move is available on the expiry day (the clamp
            # holds the current position); nothing to submit.
            self._log_decision(
                bar,
                now_ns,
                "skip-expiry-day-entry",
                reason=expiry_reason,
                target=approved_target,
                current=current_contracts,
            )
            return

        if not is_cooldown_elapsed(
            self._last_submit_ns,
            now_ns,
            self.strategy_config.cooldown_secs,
        ):
            self._log_decision(
                bar,
                now_ns,
                "skip-cooldown",
                reason=expiry_reason,
                target=approved_target,
                current=current_contracts,
            )
            return

        if is_below_min_gap(delta, self.strategy_config.min_gap_contracts):
            self._log_decision(
                bar,
                now_ns,
                "skip-gap",
                reason=expiry_reason,
                target=approved_target,
                current=current_contracts,
            )
            return

        if self._working_order_exists():
            self._log_decision(
                bar,
                now_ns,
                "skip-working",
                reason=expiry_reason,
                target=approved_target,
                current=current_contracts,
            )
            return

        if self._order_factory is None or self._instrument is None:
            self._log_decision(
                bar,
                now_ns,
                "skip-instrument-not-ready",
                reason=expiry_reason,
                target=approved_target,
                current=current_contracts,
            )
            return

        self._submit_target_delta(delta, now_ns)
        self._log_decision(
            bar,
            now_ns,
            "submit",
            reason=expiry_reason,
            target=approved_target,
            current=current_contracts,
        )

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
                f"TargetPosition {self.id} appended {appended} historical bars "
                f"(buffer={len(self._closes)}/{self.strategy_config.buffer_bars})",
            )

    # -- order event callbacks ---------------------------------------------- #

    def on_order_filled(self, event: OrderFilled) -> None:
        self._orders_filled += 1
        self._pending_client_order_ids.discard(event.client_order_id)
        self.log.info(
            f"TargetPosition {self.id} order filled: client_order_id={event.client_order_id} "
            f"instrument={event.instrument_id} side={event.order_side.name} "
            f"last_qty={event.last_qty} commission={event.commission}",
        )

    def on_order_rejected(self, event: OrderRejected) -> None:
        self._orders_rejected += 1
        self._pending_client_order_ids.discard(event.client_order_id)
        self.log.info(
            f"TargetPosition {self.id} order rejected: client_order_id={event.client_order_id} "
            f"reason={event.reason}",
        )

    def on_order_canceled(self, event: OrderCanceled) -> None:
        self._pending_client_order_ids.discard(event.client_order_id)
        self.log.info(
            f"TargetPosition {self.id} order canceled: client_order_id={event.client_order_id}",
        )

    def on_order_denied(self, event: OrderDenied) -> None:
        """Record a RiskEngine denial in telemetry and the decision log.

        With order enforcement moved to the RiskEngine (trading state driven
        by the safety monitor), denied pre-trade checks surface here instead
        of an inline controller call; the denial reason is preserved.
        """
        self._orders_denied += 1
        self._pending_client_order_ids.discard(event.client_order_id)
        self.log.info(
            f"TargetPosition {self.id} order denied: client_order_id={event.client_order_id} "
            f"reason={event.reason}",
        )
        if self.strategy_config.decision_log_path is None:
            return
        clock_ns = event.ts_event
        try:
            clock_ns = self.clock.timestamp_ns()
        except Exception:  # noqa: BLE001 - unwired clock in standalone handling
            pass
        line = format_decision(
            ts_event_ns=event.ts_event,
            clock_ns=clock_ns,
            close=self._closes[-1] if self._closes else None,
            target=None,
            current_contracts=self._current_position_contracts(),
            action="order-denied",
            reason=str(event.reason),
        )
        if not append_decision(self.strategy_config.decision_log_path, line):
            self.log.warning(
                f"TargetPosition {self.id} failed to write decision log line "
                f"(action=order-denied)",
            )

    def on_order_expired(self, event: OrderExpired) -> None:
        # DAY-TIF limit orders expire at the end of the session; clear the
        # pending set so a stale entry cannot lock out later submissions.
        self._pending_client_order_ids.discard(event.client_order_id)
        self.log.info(
            f"TargetPosition {self.id} order expired: client_order_id={event.client_order_id}",
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
        return len(self._closes) >= self.strategy_config.warmup_bars

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
                    f"TargetPosition {self.id} session re-armed for {today.isoformat()}",
                )

    def _log_decision(
        self,
        bar: Bar,
        now_ns: int,
        action: str,
        reason: str | None = None,
        target: int | None = None,
        current: int | None = None,
    ) -> None:
        """Append one decision-log line (best-effort; never raises).

        ``target`` stays null when it was not computed yet; ``current`` and
        ``close`` are read lazily when not supplied.
        """
        if self.strategy_config.decision_log_path is None:
            return
        if current is None:
            current = self._current_position_contracts()
        close = self._closes[-1] if self._closes else None
        line = format_decision(
            ts_event_ns=bar.ts_event,
            clock_ns=now_ns,
            close=close,
            target=target,
            current_contracts=current,
            action=action,
            reason=reason,
        )
        if not append_decision(self.strategy_config.decision_log_path, line):
            self.log.warning(
                f"TargetPosition {self.id} failed to write decision log line "
                f"(path={self.strategy_config.decision_log_path}, action={action})",
            )

    def _force_close(self, now: datetime) -> None:
        """Cancel all orders and close the position (idempotent per session)."""
        self.log.info(
            f"TargetPosition {self.id} force-close at {now.isoformat()} "
            f"(local {now.astimezone(VN_TZ).isoformat()})",
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
        """Signed current position in contracts, read from the Nautilus cache.

        Position source (documented choice): ``self.cache.positions(...)`` —
        ``self.portfolio`` is a facade with no per-strategy position
        accessor (only ``net_position`` across accounts), and under the
        NETTING OMS used by the entrade adapter the cache holds the single
        per-strategy position.
        """
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
        """True for an instrument-wide non-terminal order or pending strategy order."""
        open_count = len(
            self.cache.orders_open(
                instrument_id=self._instrument_id,
            ),
        )
        inflight_count = len(
            self.cache.orders_inflight(
                instrument_id=self._instrument_id,
            ),
        )
        return has_working_orders(open_count, inflight_count) or bool(
            self._pending_client_order_ids,
        )

    def _submit_target_delta(self, delta: int, ts_ns: int) -> None:
        """Submit one signed order for the position gap (deterministic
        client order id ``f"{CLIENT_ORDER_ID_PREFIX}-{timestamp_ns}"``).

        Reference price is the last trade price = latest bar close (the
        strategy consumes bars, not the book; marketable side by
        construction). ``order_style="LO"``: limit at the last close with
        ``TimeInForce.DAY`` (entrade adapter maps LIMIT+DAY -> "LO");
        ``order_style="MAK"``: market with ``TimeInForce.IOC`` (entrade
        maps MARKET+IOC -> "MAK").
        """
        if self._order_factory is None or self._instrument is None:
            self.log.warning(
                f"TargetPosition {self.id} cannot submit: instrument not ready",
            )
            return
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        quantity = self._instrument.make_qty(abs(delta))
        client_order_id = ClientOrderId(
            client_order_id_for(CLIENT_ORDER_ID_PREFIX, ts_ns),
        )

        if self.strategy_config.order_style == "MAK":
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
                    f"TargetPosition {self.id} cannot build LO: no close price buffered",
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
            f"TargetPosition {self.id} submitting {order.order_type.name} {side.name} "
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

    # -- state save/load hooks -------------------------------------------------
    # The kernel calls these via Trader.save()/load() -> Cache.update_strategy/
    # load_strategy -> database (Redis) when TradingNodeConfig.save_state/
    # load_state are set (verified in system/kernel.py + common/actor.pyx:
    # the hooks are ``on_save``/``on_load``, NOT ``on_save_state``/
    # ``on_load_state``). State dicts are msgspec-serialized by the cache
    # database adapter, so only plain JSON-compatible values are persisted.

    def on_save(self) -> dict[str, Any]:
        """Persist session and expiry-gate state so a same-day restart keeps
        the closed session and the expiry force-flat cannot re-fire.

        Returns the session date (VN), whether the session is closed, the
        last order-submission timestamp (nanoseconds), and the
        ``ExpiryState`` dates as ISO strings.
        """
        return format_target_state(
            session_date=self._session_date,
            session_closed=self._session_closed,
            last_submit_ns=self._last_submit_ns,
            expiry_state=self._expiry_state,
        )

    def on_load(self, state: dict[str, Any]) -> None:
        """Restore the expiry state (date-stamped, self-cleaning) and the
        session flags when the saved session is today's VN date.

        A new day starts fresh (the expiry/session machinery re-arms on day
        rollover anyway). Save/load errors are logged, never raised, so a
        corrupt state cannot break start-up.
        """
        try:
            saved = state.get("session_date") if isinstance(state, dict) else None
            # The expiry dates are absolute (not session-relative): the gate
            # clears a stale block on the first non-expiry bar, so restore
            # them regardless of the saved session date.
            self._expiry_state = expiry_state_from_saved(
                state.get("expiry_blocked_session_date"),
                state.get("expiry_last_processed_expiry_date"),
            )
            if not should_restore_session(saved, vn_today_iso(self._now_utc())):
                if saved is not None:
                    self.log.info(
                        f"TargetPosition {self.id}: saved session {saved} is not "
                        "today; starting fresh",
                    )
                return
            self._session_date = date.fromisoformat(saved)
            self._session_closed = bool(state.get("session_closed", False))
            last_submit_ns = state.get("last_submit_ns")
            self._last_submit_ns = (
                int(last_submit_ns) if last_submit_ns is not None else None
            )
            self.log.info(
                f"TargetPosition {self.id}: restored session state for {saved} "
                f"(closed={self._session_closed}, "
                f"last_submit_ns={self._last_submit_ns})",
            )
        except Exception as error:  # noqa: BLE001 - save/load must never break start
            self.log.warning(f"TargetPosition {self.id}: failed to load saved state: {error}")

    def _now_utc(self) -> datetime:
        """UTC now from the strategy clock, falling back to wall clock when the
        clock has no registered time source (standalone construction/tests)."""
        try:
            return self.clock.utc_now()
        except Exception:  # noqa: BLE001 - unwired clock in standalone construction
            return datetime.now(timezone.utc)
