from __future__ import annotations

import pandas as pd

from nautilus_bridge.alphas.rule_based import get_forecast_from_rules

FAST_PERIOD = 10
SLOW_PERIOD = 20


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
