"""VN30F1M front-month expiry rule (ported from nox_system) + target gate."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
EXPIRY_HOUR_LOCAL = 14
EXPIRY_MINUTE_LOCAL = 0

__all__ = [
    "EXPIRY_HOUR_LOCAL",
    "EXPIRY_MINUTE_LOCAL",
    "VN_TZ",
    "ExpiryGateDecision",
    "ExpiryState",
    "apply_expiry_gate",
    "vn30_front_month_expiry_cutoff_utc",
    "vn30_front_month_expiry_date_local",
]


@dataclass(frozen=True)
class ExpiryState:
    """Position-level state for expiry close and same-session re-entry.

    Attributes
    ----------
    blocked_session_date : date | None
        Local session date on which the position was forced flat; re-entry
        stays blocked while the session date equals it.
    last_processed_expiry_date : date | None
        Expiry date already force-processed; makes the force-flat step
        idempotent within the same day.
    """

    blocked_session_date: date | None = None
    last_processed_expiry_date: date | None = None


@dataclass(frozen=True)
class ExpiryGateDecision:
    """Outcome of applying the expiry rule to one target position.

    Attributes
    ----------
    approved_target_contracts : int
        Signed contract count the risk/execution layer may pursue.
    force_flat : bool
        True when this decision forces the position flat at the cutoff.
    reentry_blocked : bool
        True when the position was already force-flat this session and
        re-entry stays blocked until the next session.
    reason : str
        ``""`` | ``"expiry-reduce-only"`` | ``"expiry-force-close"`` |
        ``"expiry-reentry-blocked"``.
    state : ExpiryState
        State to carry into the next decision.
    """

    approved_target_contracts: int
    force_flat: bool
    reentry_blocked: bool
    reason: str
    state: ExpiryState


def apply_expiry_gate(
    ts_utc: pd.Timestamp,
    target_contracts: int,
    current_contracts: int,
    state: ExpiryState,
    *,
    enabled: bool,
    close_time_local: str = "14:00",
    tz: str = "Asia/Ho_Chi_Minh",
    working_dates: tuple[str, ...] = (),
) -> ExpiryGateDecision:
    """Apply the expiry rule to one target position at one timestamp.

    Semantics (locked):

    - ``enabled=False``: approve the target unchanged, state untouched.
    - Session date (in ``tz``) != expiry date: approve the target; a stale
      block from an earlier session is cleared.
    - Expiry day before cutoff: reduce-only — approve the target only when
      it does not increase absolute exposure vs ``current_contracts``,
      otherwise hold the current position (reason
      ``"expiry-reduce-only"``).
    - Expiry day at/after cutoff, not yet processed today: force-flat 0 and
      record both dates in the returned state (reason
      ``"expiry-force-close"``).
    - Same session after a force: approve 0 with re-entry blocked (reason
      ``"expiry-reentry-blocked"``).

    Parameters
    ----------
    ts_utc : pandas.Timestamp
        Decision timestamp (UTC).
    target_contracts : int
        Desired signed target from the portfolio layer.
    current_contracts : int
        Actual signed position observed at ``ts_utc``.
    state : ExpiryState
        State carried from the previous decision.
    enabled : bool
        Master switch for the gate (keyword-only).
    close_time_local : str
        Local expiry cutoff time ``"HH:MM"`` (default ``"14:00"``).
    tz : str
        IANA zone name used to resolve the session date.
    working_dates : tuple[str, ...]
        Market working dates (ISO strings); when given, the expiry date is
        the latest available working date on/before the third Thursday.

    Returns
    -------
    ExpiryGateDecision
        Approved target, flags, reason and the next state.

    Raises
    ------
    TypeError
        If ``ts_utc`` is timezone-naive.
    ValueError
        If ``close_time_local`` is not ``"HH:MM"``.
    """
    if not enabled:
        return ExpiryGateDecision(
            approved_target_contracts=target_contracts,
            force_flat=False,
            reentry_blocked=False,
            reason="",
            state=state,
        )
    zone = ZoneInfo(tz)
    session_date_local = ts_utc.tz_convert(zone).date()
    effective_state = _clear_previous_session_block(state, session_date_local)

    expiry_date_local = vn30_front_month_expiry_date_local(
        ts_utc,
        working_dates=working_dates,
    )
    if session_date_local != expiry_date_local:
        return ExpiryGateDecision(
            approved_target_contracts=target_contracts,
            force_flat=False,
            reentry_blocked=False,
            reason="",
            state=effective_state,
        )

    hour, minute = _parse_close_time(close_time_local)
    cutoff_utc = _expiry_cutoff_utc(ts_utc, hour, minute, working_dates)
    if (
        ts_utc >= cutoff_utc
        and effective_state.last_processed_expiry_date != session_date_local
    ):
        expiry_state = ExpiryState(
            blocked_session_date=session_date_local,
            last_processed_expiry_date=session_date_local,
        )
        return ExpiryGateDecision(
            approved_target_contracts=0,
            force_flat=True,
            reentry_blocked=False,
            reason="expiry-force-close",
            state=expiry_state,
        )

    if effective_state.blocked_session_date == session_date_local:
        return ExpiryGateDecision(
            approved_target_contracts=0,
            force_flat=False,
            reentry_blocked=True,
            reason="expiry-reentry-blocked",
            state=effective_state,
        )

    approved = (
        target_contracts
        if abs(target_contracts) <= abs(current_contracts)
        else current_contracts
    )
    return ExpiryGateDecision(
        approved_target_contracts=approved,
        force_flat=False,
        reentry_blocked=False,
        reason="expiry-reduce-only",
        state=effective_state,
    )


def vn30_front_month_expiry_cutoff_utc(
    ts_utc: pd.Timestamp,
    working_dates: tuple[str, ...] = (),
) -> pd.Timestamp:
    """Resolve the front-month expiry cutoff (local close) as UTC.

    Parameters
    ----------
    ts_utc : pandas.Timestamp
        Any timestamp inside the target month (UTC).
    working_dates : tuple[str, ...]
        Market working dates (ISO strings); may be empty to keep the raw
        third-Thursday date.

    Returns
    -------
    pandas.Timestamp
        Expiry-day cutoff at 14:00 ``Asia/Ho_Chi_Minh``, converted to UTC.

    Raises
    ------
    TypeError
        If ``ts_utc`` is timezone-naive.
    """
    return _expiry_cutoff_utc(ts_utc, EXPIRY_HOUR_LOCAL, EXPIRY_MINUTE_LOCAL, working_dates)


def vn30_front_month_expiry_date_local(
    ts_utc: pd.Timestamp,
    working_dates: tuple[str, ...] = (),
) -> date:
    """Resolve the front-month expiry trading date in local time.

    The nominal expiry is the month's third Thursday; with a working-date
    calendar the latest available working date on/before it is used.

    Parameters
    ----------
    ts_utc : pandas.Timestamp
        Any timestamp inside the target month (UTC).
    working_dates : tuple[str, ...]
        Market working dates (ISO strings); may be empty to keep the raw
        third-Thursday date.

    Returns
    -------
    datetime.date
        The resolved expiry trading date.

    Raises
    ------
    TypeError
        If ``ts_utc`` is timezone-naive.
    """
    local_ts = ts_utc.tz_convert(VN_TZ)
    target_date = date(
        local_ts.year,
        local_ts.month,
        _third_thursday(local_ts.year, local_ts.month),
    )
    return _resolve_expiry_trading_date(
        year=local_ts.year,
        month=local_ts.month,
        target_date=target_date,
        working_dates=working_dates,
    )


@lru_cache(maxsize=4096)
def _third_thursday(year: int, month: int) -> int:
    """Return the month's third Thursday day-of-month (LRU-cached)."""
    month_calendar = calendar.monthcalendar(year, month)
    thursdays = [week[calendar.THURSDAY] for week in month_calendar if week[calendar.THURSDAY] != 0]
    return thursdays[2]


def _expiry_cutoff_utc(
    ts_utc: pd.Timestamp,
    hour: int,
    minute: int,
    working_dates: tuple[str, ...],
) -> pd.Timestamp:
    """Build the expiry-day cutoff timestamp in UTC for the given local time."""
    local_ts = ts_utc.tz_convert(VN_TZ)
    expiry_day = vn30_front_month_expiry_date_local(
        ts_utc,
        working_dates=working_dates,
    ).day
    cutoff_local = pd.Timestamp(
        year=local_ts.year,
        month=local_ts.month,
        day=expiry_day,
        hour=hour,
        minute=minute,
        tz=VN_TZ,
    )
    return cutoff_local.tz_convert("UTC")


def _resolve_expiry_trading_date(
    year: int,
    month: int,
    target_date: date,
    working_dates: tuple[str, ...] | None,
) -> date:
    """Walk the nominal expiry back to the latest available working date."""
    effective_working_dates = working_dates or ()
    if not effective_working_dates:
        return target_date

    parsed_dates = sorted(pd.Timestamp(value).date() for value in effective_working_dates)
    candidates = [
        value
        for value in parsed_dates
        if value.year == year and value.month == month and value <= target_date
    ]
    if candidates:
        return candidates[-1]
    return target_date


def _clear_previous_session_block(
    state: ExpiryState,
    session_date_local: date,
) -> ExpiryState:
    """Clear a re-entry block once the session has moved past the blocked day."""
    if state.blocked_session_date is not None and session_date_local > state.blocked_session_date:
        return ExpiryState(
            blocked_session_date=None,
            last_processed_expiry_date=state.last_processed_expiry_date,
        )
    return state


def _parse_close_time(close_time_local: str) -> tuple[int, int]:
    """Parse an ``"HH:MM"`` local time string into (hour, minute)."""
    parts = close_time_local.split(":")
    if len(parts) != 2:
        raise ValueError(f"close_time_local must be 'HH:MM' (got {close_time_local!r})")
    return int(parts[0]), int(parts[1])
