from __future__ import annotations

import pandas as pd

IS_LOOKBACK = pd.DateOffset(years=2)
OS_LOOKBACK = pd.DateOffset(months=6)


def sample_window(
    sample: str,
    cutoff_day: pd.Timestamp | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    cutoff_day = cutoff_day or pd.Timestamp.now(tz="UTC").normalize()
    os_start = cutoff_day - OS_LOOKBACK

    if sample == "OS":
        return os_start, cutoff_day

    if sample == "IS":
        return cutoff_day - IS_LOOKBACK, os_start

    raise ValueError(f"sample must be 'IS' or 'OS', got {sample!r}")


def backtest_period(
    *,
    data_start: pd.Timestamp,
    data_end: pd.Timestamp,
    start: str | None = None,
    end: str | None = None,
    sample: str = "IS",
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the requested period narrowed to the first and last bar of the data."""
    window_start, window_end = sample_window(sample)

    start_ts = window_start if start is None else pd.Timestamp(start, tz="UTC")
    end_ts = window_end if end is None else pd.Timestamp(end, tz="UTC")
    # The engine runs to the period end even without bars and closes positions there
    start_ts = max(start_ts, data_start)
    end_ts = min(end_ts, data_end)

    # A year-only end such as "2026" parses to 2026-01-01 00:00, which can collapse the period
    if end_ts <= start_ts:
        raise ValueError(f"backtest end {end_ts} must be after start {start_ts}")

    return start_ts, end_ts


def period_label(start: pd.Timestamp, end: pd.Timestamp) -> str:
    dates = f"{start.date()} → {end.date()}"

    for sample in ("IS", "OS"):
        window_start, window_end = sample_window(sample)
        if window_start <= start and end <= window_end:
            return f"{sample} ({dates})"

    return dates
