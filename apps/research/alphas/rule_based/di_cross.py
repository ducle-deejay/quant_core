from __future__ import annotations

import pandas as pd

from nautilus_bridge.alphas.rule_based import get_forecast_from_rules

DI_PERIOD = 14


def alpha(bars: pd.DataFrame) -> pd.Series:
    high = bars["high"]
    low = bars["low"]
    prev_close = bars["close"].shift(1)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    true_range = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)

    def smooth(x: pd.Series) -> pd.Series:
        return x.ewm(alpha=1 / DI_PERIOD, adjust=False, min_periods=DI_PERIOD).mean()

    atr = smooth(true_range)
    plus_di = 100 * smooth(plus_dm) / atr
    minus_di = 100 * smooth(minus_dm) / atr

    entry_long = plus_di > minus_di
    entry_short = plus_di < minus_di

    forecast = get_forecast_from_rules(entry_long, entry_short)
    return forecast
