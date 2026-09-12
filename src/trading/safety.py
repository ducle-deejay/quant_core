"""Safety boundary for the live runner: pure evaluator + Nautilus monitor.

The monitor maps evaluator state to ``RiskEngine.set_trading_state``;
flattening on HALTED uses ``cancel_all_orders`` + ``close_all_positions``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import TradingState
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from core import AccountLimits
from core.contracts import Instrument
from trading.notify import format_risk_state
from trading.notify import notify_or_log

#: Local timezone for the session/rollover rules (VN derivative market).
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

#: VN local windows within which the market is open (half-open ``[start,
#: end)``). Staleness is only evaluated while the market is open: silence
#: outside these windows is expected, not a feed failure.
SESSION_WINDOWS: tuple[tuple[str, str], ...] = (
    ("09:00", "11:30"),
    ("13:00", "14:30"),
)

#: Fixed reason vocabulary of the safety boundary (mirrored by the offline
#: ``risk_limits`` policy in ``quantcore.risk``).
REASON_LOSS = "intraday-loss-limit"
REASON_STALE = "stale-feed"
REASON_EXPOSURE = "exposure-cap"

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SafetyConfig:
    """The two config-driven safety knobs (no other knobs exist).

    Parameters
    ----------
    intraday_loss_limit : float
        Session loss fraction of capital that halts trading
        (``0.02`` == 2%).
    staleness_secs : float
        Seconds without a bar (while the session is open) that halts
        trading.
    """

    intraday_loss_limit: float = 0.02
    staleness_secs: float = 60.0


def _parse_local_time(value: str):
    """Parse an ``HH:MM`` local wall-clock time (raises ``ValueError`` on garbage)."""
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid session window {value!r} (expected 'HH:MM')") from exc


def is_session_open(now: datetime, tz: ZoneInfo = VN_TZ) -> bool:
    """True while ``now``'s local time in ``tz`` falls inside ``SESSION_WINDOWS``.

    Pure function, Nautilus-free; a naive ``now`` is interpreted in ``tz``.
    """
    now_time = now.astimezone(tz).time() if now.tzinfo is not None else now.time()
    for start_str, end_str in SESSION_WINDOWS:
        if _parse_local_time(start_str) <= now_time < _parse_local_time(end_str):
            return True
    return False


def evaluate_safety(
    *,
    session_open: bool,
    now: datetime,
    last_bar_ts: datetime | None,
    staleness_secs: float,
    position: int,
    max_contracts: int,
    session_pnl_vnd: float,
    capital_vnd: float,
    intraday_loss_limit: float,
) -> tuple[TradingState, str]:
    """Evaluate the safety triggers in fixed priority (first match wins).

    Priority (same order as the safety boundary has always used):

    1. Loss: ``session_pnl_vnd <= -intraday_loss_limit * capital_vnd`` ->
       ``(HALTED, "intraday-loss-limit")``.
    2. Stale feed: ``session_open`` and ``last_bar_ts`` older than
       ``staleness_secs`` (``None`` never counts as stale) ->
       ``(HALTED, "stale-feed")``.
    3. Exposure: ``abs(position) > max_contracts`` ->
       ``(REDUCING, "exposure-cap")``.
    4. Otherwise ``(ACTIVE, "")``.

    Pure function over the given inputs (no clock, no cache); unit-testable
    without Nautilus runtime objects (the ``TradingState`` enum is a plain
    import). ``now``/``last_bar_ts`` must be comparable (tz-aware UTC
    preferred).
    """
    if session_pnl_vnd <= -intraday_loss_limit * capital_vnd:
        return TradingState.HALTED, REASON_LOSS
    if (
        session_open
        and last_bar_ts is not None
        and (now - last_bar_ts).total_seconds() > staleness_secs
    ):
        return TradingState.HALTED, REASON_STALE
    if abs(position) > max_contracts:
        return TradingState.REDUCING, REASON_EXPOSURE
    return TradingState.ACTIVE, ""


def _as_utc(ts: datetime) -> datetime:
    """Normalize to tz-aware UTC; naive timestamps are assumed UTC."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _local_date(ts: datetime, tz: ZoneInfo = VN_TZ) -> date:
    """The local calendar date of ``ts`` (the session-day key for rollover)."""
    return _as_utc(ts).astimezone(tz).date()


class SessionPnlBook:
    """Intraday PnL book of the traded strategy (positions carry, PnL resets daily).

    Feed math is byte-equivalent to the ledger that used to live in
    ``core/risk.py``: ``record_fill`` realizes ``closed_qty * (price -
    avg_entry) * multiplier`` per closing contract (opening/extending fills
    only re-weight ``avg_entry``), ``mark`` values the open position at the
    last close, ``on_bar`` advances staleness reference and rolls the
    intraday PnL over on a new Asia/Ho_Chi_Minh date. No halt state lives
    here: the monitor clears its loss latch on rollover.
    """

    def __init__(self, multiplier: float, tz: ZoneInfo = VN_TZ) -> None:
        self.multiplier = float(multiplier)
        self.tz = tz
        self.position: int = 0
        self.avg_entry: float | None = None
        self.realized_pnl_vnd: float = 0.0
        self.marked_pnl_vnd: float = 0.0
        self.intraday_date: date | None = None
        self.last_bar_ts: datetime | None = None

    def record_fill(self, price: float, qty: int, ts: datetime) -> None:
        """Accumulate one signed fill (``qty > 0`` buys/longs) into position and
        realized PnL in VND: ``closed_qty * (price - avg_entry) * multiplier``
        per contract, signed by the closing side. Opening and extending fills
        only move the weighted average entry price.
        """
        if qty == 0:
            return
        old_pos = self.position
        new_pos = old_pos + qty
        multiplier = self.multiplier

        if old_pos == 0:
            # Opening fill: nothing to realize yet.
            self.avg_entry = price if new_pos != 0 else None
        elif (old_pos > 0) == (qty > 0):
            # Same-direction extension: re-weight the average entry.
            self.avg_entry = (old_pos * (self.avg_entry or 0.0) + qty * price) / new_pos
        else:
            # Reducing or flipping: realize the closed portion.
            closing = min(abs(qty), abs(old_pos))
            direction = 1 if old_pos > 0 else -1
            self.realized_pnl_vnd += (
                closing * (price - (self.avg_entry or 0.0)) * multiplier * direction
            )
            if new_pos == 0:
                self.avg_entry = None
            elif new_pos * old_pos < 0:
                # Flipped remainder opens a new position at this price.
                self.avg_entry = price
            # else: partial close in the same direction keeps the entry price.
        self.position = new_pos

    def mark(self, price: float, ts: datetime) -> None:
        """Mark to market the current position at ``price`` (last close)."""
        if self.position == 0 or self.avg_entry is None:
            self.marked_pnl_vnd = 0.0
        else:
            self.marked_pnl_vnd = (
                self.position * (price - self.avg_entry) * self.multiplier
            )

    def on_bar(self, ts: datetime) -> None:
        """Record a bar arrival; drives the staleness reference and the day rollover.

        Positions carry across days; only the intraday PnL resets on a new
        session day (Asia/Ho_Chi_Minh date of ``ts``).
        """
        self._rollover_if_new_day(ts)
        self.last_bar_ts = _as_utc(ts)

    # -- persistence helpers (plain values, msgspec/Redis-safe) -------------

    def state_dict(self) -> dict[str, Any]:
        """Plain-values snapshot for the monitor's ``on_save`` hook."""
        return {
            "position": int(self.position),
            "avg_entry": self.avg_entry,
            "realized_pnl_vnd": float(self.realized_pnl_vnd),
            "marked_pnl_vnd": float(self.marked_pnl_vnd),
            "intraday_date": (
                self.intraday_date.isoformat() if self.intraday_date is not None else None
            ),
            "last_bar_ts": (
                self.last_bar_ts.isoformat() if self.last_bar_ts is not None else None
            ),
        }

    def load_state(self, state: dict[str, Any]) -> None:
        """Restore bookkeeping from a saved state dict; malformed values fall
        back to defaults; never raises."""
        if not isinstance(state, dict):
            return
        self.position = _to_int(state.get("position"), 0)
        avg = state.get("avg_entry")
        self.avg_entry = _to_float(avg, 0.0) if avg is not None else None
        self.realized_pnl_vnd = _to_float(state.get("realized_pnl_vnd"), 0.0)
        self.marked_pnl_vnd = _to_float(state.get("marked_pnl_vnd"), 0.0)
        self.intraday_date = _date_from_iso(state.get("intraday_date"))
        self.last_bar_ts = _dt_from_iso(state.get("last_bar_ts"))

    def _rollover_if_new_day(self, ts: datetime) -> None:
        """Reset intraday PnL when the local calendar date of ``ts`` changes."""
        day = _local_date(ts, self.tz)
        if self.intraday_date is None:
            self.intraday_date = day
            return
        if day != self.intraday_date:
            self.realized_pnl_vnd = 0.0
            self.marked_pnl_vnd = 0.0
            self.intraday_date = day


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


def _dt_from_iso(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _date_from_iso(value: Any) -> date | None:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _dt_from_ns(ns: int) -> datetime:
    """Convert a Nautilus nanosecond timestamp to a tz-aware UTC datetime."""
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


_START_STATE = "<start>"
_REASON_STARTUP = "startup"


def _append_transition(path: str, record: dict[str, Any]) -> None:
    """Append one JSONL record to ``path``; best-effort, never raises (a log
    write failure must never affect trading behavior)."""
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
            handle.flush()
    except OSError as exc:
        _LOGGER.warning("SAFETY: transition log write failed for %s: %s", path, exc)


class SafetyMonitor(Strategy):
    """Live safety monitor: bars + position events + timer in, trading state out.

    On every bar/timer tick the monitor updates the :class:`SessionPnlBook`
    (fills derived from position-event deltas, marks from the last bar
    close), evaluates :func:`evaluate_safety`, and ON STATE CHANGE drives
    ``risk_engine.set_trading_state(state)`` (a direct method on the injected
    engine, NOT a msgbus send) plus the transition JSONL and notifier. On the
    transition INTO HALTED it cancels all orders and closes all positions.
    The loss halt latches until the book's day rollover; the stale halt
    clears as soon as a fresh bar arrives (the flatten already ran).
    """

    def __init__(
        self,
        *,
        instrument_id: str,
        bar_type: str | BarType,
        safety: SafetyConfig,
        limits: AccountLimits,
        risk_engine: Any,
        monitor_strategy_id: str,
        bridge_strategy_id: str,
        transition_log_path: str | None = None,
        notifier: Any = None,
    ) -> None:
        if not isinstance(safety, SafetyConfig):
            raise TypeError(f"safety must be a SafetyConfig, got {type(safety).__name__}")
        if not isinstance(limits, AccountLimits):
            raise TypeError(f"limits must be an AccountLimits, got {type(limits).__name__}")
        if not monitor_strategy_id.strip():
            raise ValueError("monitor_strategy_id must be a non-empty string")
        if not bridge_strategy_id.strip():
            raise ValueError("bridge_strategy_id must be a non-empty string")
        # Nautilus composes the final id as f"{ClassName}-{order_id_tag}"
        # (verified: an explicit strategy_id gets the tag appended again), so
        # ``monitor_strategy_id`` must match that form for this class and the
        # tag is its tail.
        tag = monitor_strategy_id.rsplit("-", 1)[-1].strip()
        if not tag or monitor_strategy_id != f"SafetyMonitor-{tag}":
            raise ValueError(
                f"monitor_strategy_id must be 'SafetyMonitor-<tag>', got {monitor_strategy_id!r}",
            )
        super().__init__(config=StrategyConfig(order_id_tag=tag))
        self._instrument_id = (
            instrument_id if isinstance(instrument_id, InstrumentId) else InstrumentId.from_str(str(instrument_id))
        )
        self._bar_type = bar_type if isinstance(bar_type, BarType) else BarType.from_str(str(bar_type))
        if self._bar_type.instrument_id != self._instrument_id:
            raise ValueError(
                f"bar_type instrument {self._bar_type.instrument_id} does not match "
                f"instrument_id {self._instrument_id}",
            )
        self._safety = safety
        self._limits = limits
        self._risk_engine = risk_engine
        self._monitor_strategy_id = monitor_strategy_id
        self._bridge_strategy_id = bridge_strategy_id
        self._transition_log_path = transition_log_path
        self._notifier = notifier  # duck-typed: notify(text) or None
        self._position_topic = f"events.position.{bridge_strategy_id}"
        self._timer_name = f"SAFETY_STALENESS:{self._instrument_id}"

        # Reference-data multiplier (core owns the instrument definitions).
        symbol = str(self._instrument_id).split(".", 1)[0]
        self._book = SessionPnlBook(multiplier=Instrument.load(symbol).multiplier)

        self._last_state: TradingState | None = None
        self._last_reason: str = ""
        #: Day (local) the loss halt latched on; None = not latched. Cleared
        #: by the monitor when the book rolls to a new day.
        self._loss_latch_day: date | None = None
        self._last_mark_price: float | None = None
        #: Last signed quantity per position id (fill deltas from events).
        self._signed_qty_by_position: dict[str, int] = {}

    @property
    def instrument_id(self):
        """The monitored instrument id."""
        return self._instrument_id

    @property
    def safety_config(self) -> SafetyConfig:
        """The safety thresholds driving the evaluator."""
        return self._safety

    # -- lifecycle -----------------------------------------------------------

    def on_start(self) -> None:
        """Subscribe to bars and bridge position events; arm the staleness timer."""
        self.subscribe_bars(self._bar_type)
        self.msgbus.subscribe(topic=self._position_topic, handler=self._on_bridge_position_event)
        self.log.info(
            f"SAFETY: subscribing to bridge position events topic={self._position_topic}",
        )
        self.clock.set_timer(
            name=self._timer_name,
            interval=timedelta(seconds=1.0),
            callback=self._on_timer,
        )
        self._evaluate(self._now_utc())
        self.log.info(
            f"SAFETY: monitor started instrument={self._instrument_id} "
            f"bar_type={self._bar_type}",
        )

    def on_stop(self) -> None:
        """Cancel the timer and drop the position-event subscription."""
        if self._timer_name in self.clock.timer_names:
            self.clock.cancel_timer(self._timer_name)
        self.msgbus.unsubscribe(
            topic=self._position_topic, handler=self._on_bridge_position_event
        )
        self.log.info("SAFETY: monitor stopped")

    # -- data / event handlers ----------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        """Roll the book on a fresh bar (stale halt clears here) and re-evaluate."""
        if bar.bar_type != self._bar_type:
            return
        ts = _dt_from_ns(bar.ts_event)
        close = bar.close.as_double()
        self._book.on_bar(ts)
        self._book.mark(close, ts)
        self._last_mark_price = close
        self._evaluate(self._now_utc())

    def on_position_event(self, event) -> None:
        """Own flatten fills also feed the book (position-event deltas)."""
        self._apply_position_delta(event)

    def _on_bridge_position_event(self, event) -> None:
        """Fill feed for the monitored strategy (msgbus topic subscription)."""
        self._apply_position_delta(event)

    def _apply_position_delta(self, event) -> None:
        """Derive one signed fill from a position-event quantity delta."""
        if getattr(event, "instrument_id", None) != self._instrument_id:
            return
        position_key = str(getattr(event, "position_id", ""))
        try:
            signed = int(event.signed_qty)
        except (TypeError, ValueError, AttributeError):
            return
        previous = self._signed_qty_by_position.get(position_key)
        delta = signed if previous is None else signed - previous
        self._signed_qty_by_position[position_key] = signed
        if delta == 0:
            return
        price = self._event_price(event)
        self._book.record_fill(price, delta, _dt_from_ns(event.ts_event))
        self._evaluate(self._now_utc())

    @staticmethod
    def _event_price(event) -> float:
        """Fill price of a position event: ``last_px``, falling back to the
        open average (adjusted/restored events carry no last fill)."""
        last_px = getattr(event, "last_px", None)
        if last_px is not None:
            try:
                return float(last_px.as_double())
            except AttributeError:
                return float(last_px)
        return float(getattr(event, "avg_px_open", 0.0) or 0.0)

    def _on_timer(self, _event) -> None:
        """Dead-man's switch tick: re-mark with the last close so staleness is
        detectable even when the feed is silent, then re-evaluate."""
        now = self._now_utc()
        if self._last_mark_price is not None:
            self._book.mark(self._last_mark_price, now)
        self._evaluate(now)

    # -- evaluation ----------------------------------------------------------

    def _now_utc(self) -> datetime:
        """UTC now from the strategy clock, falling back to wall clock when the
        clock has no registered time source (standalone construction/tests)."""
        try:
            return self.clock.utc_now()
        except Exception:  # noqa: BLE001 - unwired clock in standalone construction
            return datetime.now(timezone.utc)

    def _evaluate(self, now: datetime) -> None:
        """Evaluate the safety state and act on every state change."""
        book = self._book
        if (
            self._loss_latch_day is not None
            and book.intraday_date is not None
            and book.intraday_date != self._loss_latch_day
        ):
            # Day rollover: the book reset the intraday PnL; the monitor
            # clears the loss latch (fresh loss budget).
            self._loss_latch_day = None
            self.log.info("SAFETY: loss halt cleared by day rollover")

        if self._loss_latch_day is not None:
            state, reason = TradingState.HALTED, REASON_LOSS
        else:
            state, reason = evaluate_safety(
                session_open=is_session_open(now),
                now=now,
                last_bar_ts=book.last_bar_ts,
                staleness_secs=self._safety.staleness_secs,
                position=book.position,
                max_contracts=self._limits.max_contracts,
                session_pnl_vnd=book.realized_pnl_vnd + book.marked_pnl_vnd,
                capital_vnd=self._limits.capital_vnd,
                intraday_loss_limit=self._safety.intraday_loss_limit,
            )
        if state == TradingState.HALTED and reason == REASON_LOSS:
            self._loss_latch_day = book.intraday_date

        if (state, reason) == (self._last_state, self._last_reason):
            return
        previous = self._last_state
        self._last_state, self._last_reason = state, reason

        # Direct engine call (the RiskEngine instance is injected; the
        # trading state is NOT sent over the msgbus).
        self._risk_engine.set_trading_state(state)
        self.log.warning(
            f"SAFETY: trading state "
            f"{previous.name if previous is not None else _START_STATE} -> {state.name} "
            f"({reason or 'ok'}); RiskEngine.set_trading_state applied",
        )
        self._write_transition(previous, state, reason)
        notify_or_log(
            self._notifier,
            format_risk_state(
                previous.name if previous is not None else _START_STATE,
                state.name,
                reason or "ok",
            ),
        )
        if state == TradingState.HALTED and reason in (REASON_LOSS, REASON_STALE):
            self.log.warning(
                f"SAFETY: HALTED ({reason}) - canceling all orders and closing "
                f"all positions for {self._instrument_id}",
            )
            self.cancel_all_orders(self._instrument_id)
            self.close_all_positions(self._instrument_id)

    def _write_transition(self, previous: TradingState | None, current: TradingState, reason: str) -> None:
        """Append one JSONL record per state change; a no-op without a path."""
        if self._transition_log_path is None:
            return
        record = {
            "ts_ns": time.time_ns(),
            "previous": previous.name if previous is not None else _START_STATE,
            "current": current.name,
            "reason": _REASON_STARTUP if previous is None else (reason or None),
        }
        _append_transition(self._transition_log_path, record)

    # -- state save/load hooks --------------------------------------------------

    def on_save(self) -> dict[str, Any]:
        """Persist the book and the current safety state so a restart keeps
        the halt latch and the PnL math identical (kernel save hook)."""
        return {
            "book": self._book.state_dict(),
            "state": self._last_state.name if self._last_state is not None else None,
            "reason": self._last_reason,
            "loss_latch_day": (
                self._loss_latch_day.isoformat() if self._loss_latch_day is not None else None
            ),
            "last_mark_price": self._last_mark_price,
        }

    def on_load(self, state: dict[str, Any]) -> None:
        """Restore book and state; a persisted HALTED loss latch stays latched
        for the same day (no silent re-arm). Save/load errors are logged,
        never raised, so a corrupt state cannot break start-up."""
        try:
            if not isinstance(state, dict):
                return
            self._book.load_state(state.get("book"))
            self._last_reason = str(state.get("reason") or "")
            saved_state = state.get("state")
            self._last_state = (
                TradingState[saved_state] if saved_state in TradingState.__members__ else None
            )
            self._loss_latch_day = _date_from_iso(state.get("loss_latch_day"))
            self._last_mark_price = _to_float(state.get("last_mark_price"), 0.0) or None
            if self._loss_latch_day is not None:
                self.log.warning(
                    "SAFETY: restored latched loss halt from saved state - "
                    "trading stays halted until the day rollover"
                )
        except Exception as error:  # noqa: BLE001 - save/load must never break start
            self.log.warning(f"SAFETY: failed to load saved state: {error}")
