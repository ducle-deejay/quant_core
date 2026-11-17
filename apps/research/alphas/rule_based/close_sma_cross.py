from __future__ import annotations

import pandas as pd

from nautilus_bridge.alphas.rule_based import get_forecast_from_rules

SMA_PERIOD = 50


def alpha(bars: pd.DataFrame) -> pd.Series:
    close = bars["close"]
    sma = close.rolling(SMA_PERIOD).mean()

    entry_long = close > sma
    entry_short = close < sma

    forecast = get_forecast_from_rules(entry_long, entry_short)
    return forecast
