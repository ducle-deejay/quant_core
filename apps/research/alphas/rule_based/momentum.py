from __future__ import annotations

import pandas as pd

from nautilus_bridge.alphas.rule_based import get_forecast_from_rules

RETURN_PERIOD = 20


def alpha(bars: pd.DataFrame) -> pd.Series:
    close = bars["close"]
    ret = close / close.shift(RETURN_PERIOD) - 1

    entry_long = ret > 0
    entry_short = ret < 0

    forecast = get_forecast_from_rules(entry_long, entry_short)
    return forecast
