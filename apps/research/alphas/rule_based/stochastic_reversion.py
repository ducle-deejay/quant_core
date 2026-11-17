from __future__ import annotations

import pandas as pd

from nautilus_bridge.alphas.rule_based import get_forecast_from_rules

STOCHASTIC_PERIOD = 14
OVERSOLD = 20
OVERBOUGHT = 80


def alpha(bars: pd.DataFrame) -> pd.Series:
    close = bars["close"]
    lowest = bars["low"].rolling(STOCHASTIC_PERIOD).min()
    highest = bars["high"].rolling(STOCHASTIC_PERIOD).max()
    stochastic = 100 * (close - lowest) / (highest - lowest)

    entry_long = stochastic < OVERSOLD
    entry_short = stochastic > OVERBOUGHT

    forecast = get_forecast_from_rules(entry_long, entry_short)
    return forecast
