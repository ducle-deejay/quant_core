from __future__ import annotations

import numpy as np
import pandas as pd


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
