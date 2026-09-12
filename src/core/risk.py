"""Shared risk state machine — the single RiskLedger for research AND live.
Pure stdlib + ``core.contracts`` types (no Nautilus).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from .contracts import RiskConfig, RiskDecision, RiskState, TargetPosition

# --- status vocabulary (soft-halt ladder; shutdown out of scope) ------------
ACTIVE = "ACTIVE"
HALTED = "HALTED"
REDUCING = "REDUCING"

# --- reason vocabulary ------------------------------------------------------
REASON_LOSS = "intraday-loss-limit"
REASON_STALE = "stale-feed"
REASON_EXPOSURE = "exposure-cap"
REASON_EXCEEDS_MAX = "exceeds-max-contracts"
REASON_REDUCING_ONLY = "reducing-only"


# --- session helpers (pure functions) ---------------------------------------

def parse_close_time(value: str) -> time:
    """Parse an ``HH:MM`` local wall-clock close time."""
    try:
        hour_text, minute_text = value.split(":", 1)
        return time(int(hour_text), int(minute_text))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid session close time {value!r} (expected 'HH:MM')") from exc


def in_tz(ts: datetime, tz: str) -> datetime:
    """Project ``ts`` into ``tz``; a naive ``ts`` is interpreted in ``tz``."""
    zone = ZoneInfo(tz)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=zone)
    return ts.astimezone(zone)


def is_session_open(ts: datetime, session_close_local_time: str, tz: str) -> bool:
    """True while the local wall-clock time of ``ts`` is before the session close.

    Pure function, Nautilus-free. The session is considered open from local
    midnight up to (not including) the configured close time; overnight
    sessions are out of scope for this market (VN30 trades same local date).
    """
    local = in_tz(ts, tz)
    return local.time() < parse_close_time(session_close_local_time)


def session_day(ts: datetime, tz: str) -> date:
    """The local calendar date of ``ts``; the session-day key for rollover."""
    return in_tz(ts, tz).date()


def _as_utc(ts: datetime) -> datetime:
    """Normalize to tz-aware UTC; naive timestamps are assumed UTC."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


@dataclass
class RiskLedger:
    """Mutable risk state fed by fills, bars, and marks.

    Public state fields (the telemetry surface): ``status``, ``reason``,
    ``realized_pnl_vnd`` (accumulated from fills), ``marked_pnl_vnd``
    (mark-to-market at the last close), ``last_bar_ts``, ``last_bar_seen_session``
    (whether that bar arrived while the session was open), ``intraday_start_ts``.

    Only ``decide()`` mutates status/reason; every other method feeds state.
    """

    config: RiskConfig
    status: str = ACTIVE
    reason: str = ""
    realized_pnl_vnd: float = 0.0
    marked_pnl_vnd: float = 0.0
    last_bar_ts: datetime | None = None
    last_bar_seen_session: bool = False
    intraday_start_ts: datetime | None = None
    # Derived state (not constructor arguments)
    position: int = field(default=0, init=False)  # signed contracts from fills
    avg_entry: float | None = field(default=None, init=False)
    last_price: float | None = field(default=None, init=False)
    _now_ts: datetime | None = field(default=None, init=False)

    # -- event feed ---------------------------------------------------------

    def record_fill(self, price: float, qty: int, ts: datetime) -> None:
        """Accumulate one signed fill (``qty > 0`` buys/longs) into position and
        realized PnL in VND: ``closed_qty * (price - avg_entry) * multiplier``
        per contract, signed by the closing side. Opening and extending fills
        only move the weighted average entry price.
        """
        if qty == 0:
            return
        ts = _as_utc(ts)
        self._touch(ts)
        self._rollover_if_new_day(ts)

        old_pos = self.position
        new_pos = old_pos + qty
        multiplier = self.config.instrument.multiplier

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
        ts = _as_utc(ts)
        self._touch(ts)
        self.last_price = price
        if self.position == 0 or self.avg_entry is None:
            self.marked_pnl_vnd = 0.0
        else:
            self.marked_pnl_vnd = (
                self.position * (price - self.avg_entry) * self.config.instrument.multiplier
            )

    def on_bar(self, ts: datetime) -> None:
        """Record a bar arrival; drives staleness and the day rollover."""
        ts = _as_utc(ts)
        self._touch(ts)
        self._rollover_if_new_day(ts)
        self.last_bar_ts = ts
        self.last_bar_seen_session = is_session_open(
            ts, self.config.session_close_local_time, self.config.tz
        )

    def reconcile_position(self, contracts: int, avg_entry: float | None = None) -> None:
        """Seed the ledger from an external position view (e.g. the cache
        snapshot restored at start-up); does not touch intraday PnL."""
        self.position = contracts
        self.avg_entry = avg_entry if contracts != 0 else None

    # -- decision ------------------------------------------------------------

    def decide(self) -> RiskState:
        """Evaluate the trigger matrix in fixed priority and mutate status.

        Priority order (first match wins): 1. realized+marked <=
        ``-intraday_loss_limit * capital_vnd`` -> HALTED
        ``intraday-loss-limit``; 2. no bar within ``staleness_secs`` while
        the session is open -> HALTED ``stale-feed``; 3. ``|position| >
        max_contracts`` -> REDUCING ``exposure-cap``; 4. otherwise ACTIVE.

        Staleness additionally requires a time reference (``_now_ts``, set by
        any mark/bar/fill), an in-session last bar, and an open session at
        ``now``; before any event is observed the ledger returns ACTIVE.
        """
        now = self._now_ts

        if (
            self.realized_pnl_vnd + self.marked_pnl_vnd
            <= -self.config.intraday_loss_limit * self.config.limits.capital_vnd
        ):
            self.status, self.reason = HALTED, REASON_LOSS
        elif (
            now is not None
            and self.last_bar_ts is not None
            and self.last_bar_seen_session
            and is_session_open(now, self.config.session_close_local_time, self.config.tz)
            and (now - self.last_bar_ts).total_seconds() > self.config.staleness_secs
        ):
            self.status, self.reason = HALTED, REASON_STALE
        elif abs(self.position) > self.config.limits.max_contracts:
            self.status, self.reason = REDUCING, REASON_EXPOSURE
        else:
            self.status, self.reason = ACTIVE, ""

        return RiskState(status=self.status, reason=self.reason)

    def gate(self, target_contracts: int, current_contracts: int) -> tuple[bool, str]:
        """Gate one target move against the current status.

        HALTED   -> deny everything (reason prefixed with the halt reason).
        REDUCING -> allow only moves that strictly reduce |position|.
        ACTIVE   -> allow iff |target| <= max_contracts, else deny
                    ``exceeds-max-contracts``.
        """
        if self.status == HALTED:
            return False, f"halted:{self.reason}"
        if self.status == REDUCING:
            if abs(target_contracts) < abs(current_contracts):
                return True, ""
            return False, REASON_REDUCING_ONLY
        if abs(target_contracts) <= self.config.limits.max_contracts:
            return True, ""
        return False, REASON_EXCEEDS_MAX

    def decide_target(
        self,
        target: TargetPosition,
        current_contracts: int | None = None,
    ) -> RiskDecision:
        """Map the existing gate and trigger matrix to the canonical decision.

        ``current_contracts`` may be supplied by the Nautilus cache; the
        ledger position remains the fallback for pure/offline callers.
        Existing loss and stale-feed halts are emergency force-flat actions.
        Other denials retain the actual position as a blocked target.
        """
        if not isinstance(target, TargetPosition):
            raise TypeError("target must be a TargetPosition")
        current = self.position if current_contracts is None else current_contracts
        if isinstance(current, bool) or not isinstance(current, int):
            raise TypeError("current_contracts must be an integer")
        # Refresh status before mapping so a decision cannot observe stale
        # trigger state.  The overlay's latch is applied outside this pure
        # ledger method.
        state = self.decide()
        if state.status == HALTED and state.reason in (REASON_LOSS, REASON_STALE):
            return RiskDecision(target, 0, "force-flat", state.reason, current)
        allowed, gate_reason = self.gate(target.target_contracts, current)
        if allowed:
            return RiskDecision(
                target,
                target.target_contracts,
                "approve",
                state.reason or "within-risk-limits",
                current,
            )
        return RiskDecision(
            target,
            current,
            "block",
            gate_reason or state.reason or "risk-policy-denied",
            current,
        )

    # -- internals -----------------------------------------------------------

    def _touch(self, ts: datetime) -> None:
        """Advance the time reference; timestamps are monotonic (max)."""
        if self._now_ts is None or ts > self._now_ts:
            self._now_ts = ts

    def _rollover_if_new_day(self, ts: datetime) -> None:
        """Reset intraday PnL (and lift a loss halt) when a new session day starts.

        Positions carry across days; only the intraday PnL resets — a fresh
        day starts with a fresh loss budget.
        """
        if self.intraday_start_ts is None:
            self.intraday_start_ts = ts
            return
        if session_day(ts, self.config.tz) != session_day(self.intraday_start_ts, self.config.tz):
            self.realized_pnl_vnd = 0.0
            self.marked_pnl_vnd = 0.0
            self.intraday_start_ts = ts
            if self.status == HALTED and self.reason == REASON_LOSS:
                self.status = ACTIVE
                self.reason = ""
