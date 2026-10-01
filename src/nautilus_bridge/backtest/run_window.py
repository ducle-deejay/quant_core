from __future__ import annotations

import pandas as pd

IS_LOOKBACK = pd.DateOffset(years=2)
OS_LOOKBACK = pd.DateOffset(months=6)


def sample_window(
    mode: str,
    cutoff_day: pd.Timestamp | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    cutoff_day = cutoff_day or pd.Timestamp.now(tz="UTC").normalize()
    os_start = cutoff_day - OS_LOOKBACK

    if mode == "OS":
        return os_start, cutoff_day

    if mode == "IS":
        return cutoff_day - IS_LOOKBACK, os_start

    raise ValueError(f"mode must be 'IS' or 'OS', got {mode!r}")


def backtest_period(
    start: str | None = None,
    end: str | None = None,
    mode: str = "IS",
) -> tuple[pd.Timestamp, pd.Timestamp]:
    window_start, window_end = sample_window(mode)

    start_ts = window_start if start is None else pd.Timestamp(start, tz="UTC")
    end_ts = window_end if end is None else pd.Timestamp(end, tz="UTC")

    return start_ts, end_ts


def period_label(start: pd.Timestamp, end: pd.Timestamp) -> str:
    dates = f"{start.date()} → {end.date()}"

    for mode in ("IS", "OS"):
        if (start, end) == sample_window(mode):
            return f"{mode} ({dates})"

    return dates
