from __future__ import annotations

import pandas as pd

from nautilus_bridge.alphas.rule_based import get_forecast_from_rules

BAND_PERIOD = 20
BAND_STD = 2.0


def alpha(bars: pd.DataFrame) -> pd.Series:
    close = bars["close"]
    middle = close.rolling(BAND_PERIOD).mean()
    std = close.rolling(BAND_PERIOD).std()
    lower = middle - BAND_STD * std
    upper = middle + BAND_STD * std

    entry_long = close < lower
    entry_short = close > upper

    forecast = get_forecast_from_rules(entry_long, entry_short)
    return forecast
