from __future__ import annotations

import math

import pandas as pd

from nautilus_bridge.analyzer.statistics import TRADING_DAYS_PER_YEAR


def forecast_statistics(
    forecast: pd.Series,
    close: pd.Series,
    bars_per_day: int,
    multiplier: float,
    commission_per_contract: float,
    horizon_bars: int = 1,  # Bars a position is held before the next forecast can change it
) -> dict[str, float]:
    forward_change = close.shift(-horizon_bars) - close
    ic = forecast.corr(forward_change / close)
    pnl = forecast * forward_change * multiplier
    cost = forecast.diff(horizon_bars).abs() * commission_per_contract
    bets_per_year = TRADING_DAYS_PER_YEAR * bars_per_day / horizon_bars
    return {
        f"Sharpe Ratio (IC-based, {TRADING_DAYS_PER_YEAR} days)": (
            (ic - cost.mean() / pnl.std()) * math.sqrt(bets_per_year)
        ),
        f"IC (Pearson, {horizon_bars} bar)": ic,
    }
