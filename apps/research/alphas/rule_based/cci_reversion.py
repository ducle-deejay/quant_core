from __future__ import annotations

import pandas as pd

from nautilus_bridge.alphas.rule_based import get_forecast_from_rules

CCI_PERIOD = 20
CCI_CONSTANT = 0.015
OVERSOLD = -100
OVERBOUGHT = 100


def rolling_mean_abs_deviation(x: pd.Series, period: int) -> pd.Series:
    return x.rolling(period).apply(lambda window: (window - window.mean()).abs().mean(), raw=False)


def alpha(bars: pd.DataFrame) -> pd.Series:
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3
    mean = typical.rolling(CCI_PERIOD).mean()
    mean_deviation = rolling_mean_abs_deviation(typical, CCI_PERIOD)
    cci = (typical - mean) / (CCI_CONSTANT * mean_deviation)

    entry_long = cci < OVERSOLD
    entry_short = cci > OVERBOUGHT

    forecast = get_forecast_from_rules(entry_long, entry_short)
    return forecast
