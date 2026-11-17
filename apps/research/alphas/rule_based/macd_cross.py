from __future__ import annotations

import pandas as pd

from nautilus_bridge.alphas.rule_based import get_forecast_from_rules

FAST_PERIOD = 12
SLOW_PERIOD = 26
SIGNAL_PERIOD = 9


def alpha(bars: pd.DataFrame) -> pd.Series:
    close = bars["close"]
    fast = close.ewm(span=FAST_PERIOD, adjust=False, min_periods=FAST_PERIOD).mean()
    slow = close.ewm(span=SLOW_PERIOD, adjust=False, min_periods=SLOW_PERIOD).mean()
    macd = fast - slow
    signal = macd.ewm(span=SIGNAL_PERIOD, adjust=False, min_periods=SIGNAL_PERIOD).mean()

    entry_long = macd > signal
    entry_short = macd < signal

    forecast = get_forecast_from_rules(entry_long, entry_short)
    return forecast
