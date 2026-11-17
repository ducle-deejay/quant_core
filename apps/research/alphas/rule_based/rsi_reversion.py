from __future__ import annotations

import pandas as pd

from nautilus_bridge.alphas.rule_based import get_forecast_from_rules

RSI_PERIOD = 14
OVERSOLD = 30
OVERBOUGHT = 70


def alpha(bars: pd.DataFrame) -> pd.Series:
    change = bars["close"].diff()
    gain = change.clip(lower=0).ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    loss = (-change).clip(lower=0).ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    rsi = 100 - 100 / (1 + gain / loss)

    entry_long = rsi < OVERSOLD
    entry_short = rsi > OVERBOUGHT

    forecast = get_forecast_from_rules(entry_long, entry_short)
    return forecast
