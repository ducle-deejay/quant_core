from __future__ import annotations

import numpy as np
import pandas as pd

FAST_PERIOD = 10
SLOW_PERIOD = 20


def get_forecast_from_rules(
    entry_long: pd.Series,
    entry_short: pd.Series,
    exit_long: pd.Series | None = None,
    exit_short: pd.Series | None = None,
) -> pd.Series:
    no_exit = pd.Series(False, index=entry_long.index)
    exit_long = no_exit if exit_long is None else exit_long
    exit_short = no_exit if exit_short is None else exit_short

    long = pd.Series(np.nan, index=entry_long.index)
    long[exit_long | entry_short] = 0.0
    long[entry_long & ~entry_short] = 1.0

    short = pd.Series(np.nan, index=entry_short.index)
    short[exit_short | entry_long] = 0.0
    short[entry_short & ~entry_long] = 1.0

    forecast = long.ffill() - short.ffill()
    return forecast


def alpha(bars: pd.DataFrame) -> pd.Series:
    close = bars["close"]
    fast = close.ewm(span=FAST_PERIOD, adjust=False, min_periods=FAST_PERIOD).mean()
    slow = close.ewm(span=SLOW_PERIOD, adjust=False, min_periods=SLOW_PERIOD).mean()

    entry_long = fast >= slow
    entry_short = fast < slow
    exit_long = None
    exit_short = None

    forecast = get_forecast_from_rules(entry_long, entry_short, exit_long, exit_short)
    return forecast
