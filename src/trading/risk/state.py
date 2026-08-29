"""Component 7 risk state machine - pure, Nautilus-free core.

This module holds the entire risk *decision* surface of the live wiring phase
(workstream C): configuration, the state ledger, the trigger matrix, gate
semantics, and the session/day-rollover helpers. It imports only the standard
library plus the Nautilus-free contract types from ``trading.contracts``, so
every behaviour here is unit-testable without a Nautilus runtime. The thin
Nautilus integration lives in ``trading.risk.overlay`` and drives this core.

Governing design (frozen canon, docs/enhanced/):
- STG-7-RISK-OVERLAY : layer-3 ladder (soft halt / flatten / shutdown) minus
  shutdown; layer-2 exposure caps; layer-3 dead-man's switch (stale feed).
- DEC-008 : built to live standard from the paper phase; risk runs in the same
  TradingNode as the strategy for milestone 1 (accepted gap, tracked there).
- OBS-009 / OBS-010 : entrade margin basis and 100,000 VND contract multiplier.

Trigger matrix (priority order, first match wins):
  | priority | condition                                   | status   | reason                |
  |----------+---------------------------------------------+----------+-----------------------|
  | 1        | realized+marked <= -intraday_loss_pct*cap   | HALTED   | intraday-loss-limit   |
  | 2        | no bar within staleness_secs, session open  | HALTED   | stale-feed            |
  | 3        | |position| > max_contracts                  | REDUCING | exposure-cap          |
  | 4        | otherwise                                   | ACTIVE   |                       |

Loss-limit and exposure checks run on every ``decide()`` regardless of time
reference; the staleness check additionally requires an observed ``now`` and
that the last bar was seen during an open session (see ``RiskLedger.decide``).

Day rollover: the intraday loss limit is per trading session day. When the
first event of a new local session day arrives, the intraday PnL counters are
reset and a loss halt is lifted (a fresh day starts with a fresh loss budget).
Positions carry across days; only the intraday PnL resets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from trading.contracts import RiskState

# --- status vocabulary (canon STG-7 layer 3, shutdown out of scope) ---------
ACTIVE = "ACTIVE"
HALTED = "HALTED"
REDUCING = "REDUCING"

# --- reason vocabulary ------------------------------------------------------
REASON_LOSS = "intraday-loss-limit"
REASON_STALE = "stale-feed"
REASON_EXPOSURE = "exposure-cap"
REASON_EXCEEDS_MAX = "exceeds-max-contracts"
REASON_REDUCING_ONLY = "reducing-only"


@dataclass(frozen=True)
class RiskConfig:
    """Component 7 configuration (layer-2 cap + layer-3 triggers).

    Milestone-1 facts baked into the defaults (DEC-008, OBS-009/OBS-010):
    capital 100,000,000 VND; entrade margin 5% maps to ``max_contracts`` via
    the orchestration L_max formula; contract multiplier 100,000 VND/point.
    """

    capital_vnd: float = 100_000_000.0
    max_contracts: int = 10
    intraday_loss_pct: float = 0.02
    staleness_secs: float = 60.0
    session_close_local_time: str = "14:00"
    tz: str = "Asia/Ho_Chi_Minh"
    flatten_max_attempts: int = 3
    flatten_retry_secs: float = 1.0
    contract_multiplier: float = 100_000.0


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
    """Mutable Component 7 risk state fed by fills, bars, and marks.

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
        multiplier = self.config.contract_multiplier

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
                self.position * (price - self.avg_entry) * self.config.contract_multiplier
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

        Staleness additionally requires a time reference (``_now_ts``, set by
        any mark/bar/fill), an in-session last bar, and an open session at
        ``now``; before any event is observed the ledger returns ACTIVE.
        """
        now = self._now_ts

        if (
            self.realized_pnl_vnd + self.marked_pnl_vnd
            <= -self.config.intraday_loss_pct * self.config.capital_vnd
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
        elif abs(self.position) > self.config.max_contracts:
            self.status, self.reason = REDUCING, REASON_EXPOSURE
        else:
            self.status, self.reason = ACTIVE, ""

        return RiskState(status=self.status, reason=self.reason)

    # -- gate ----------------------------------------------------------------

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
        if abs(target_contracts) <= self.config.max_contracts:
            return True, ""
        return False, REASON_EXCEEDS_MAX

    # -- internals -----------------------------------------------------------

    def _touch(self, ts: datetime) -> None:
        """Advance the time reference; timestamps are monotonic (max)."""
        if self._now_ts is None or ts > self._now_ts:
            self._now_ts = ts

    def _rollover_if_new_day(self, ts: datetime) -> None:
        """Reset intraday PnL (and lift a loss halt) when a new session day starts."""
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
