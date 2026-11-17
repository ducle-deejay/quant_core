from __future__ import annotations

import pandas as pd

from nautilus_bridge.alphas.rule_based import get_forecast_from_rules

CHANNEL_PERIOD = 20


def alpha(bars: pd.DataFrame) -> pd.Series:
    close = bars["close"]
    prior_high = bars["high"].rolling(CHANNEL_PERIOD).max().shift(1)
    prior_low = bars["low"].rolling(CHANNEL_PERIOD).min().shift(1)

    entry_long = close > prior_high
    entry_short = close < prior_low

    forecast = get_forecast_from_rules(entry_long, entry_short)
    return forecast
