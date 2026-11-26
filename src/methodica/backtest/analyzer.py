import pandas as pd
from nautilus_trader.analysis import (
    MaxDrawdown,
    ReturnsAverage,
    ReturnsVolatility,
    SharpeRatio,
)

from methodica.common.metrics import turnover
from nautilus_bridge.alphas.session_resampling import bars_per_day
from nautilus_bridge.analyzer.analyzer import ordered_stats
from nautilus_bridge.analyzer.forecast_statistics import forecast_statistics

RETURN_STATISTICS = [SharpeRatio, ReturnsAverage, ReturnsVolatility, MaxDrawdown]


def performance_statistics(results, forecast_col, book_size, timeframe, horizon, multiplier, cost_per_contract):
    equity = (book_size + results.net_pnl.fillna(0).cumsum()).tz_convert("UTC")
    days = pd.date_range(equity.index[0].normalize(), equity.index[-1].normalize(), freq="D", tz="UTC")
    daily_returns = (
        equity.groupby(equity.index.normalize()).last()
        .reindex(days).ffill().fillna(book_size)
        .pct_change().fillna(0)
    )
    returns = {int(ts.value): r for ts, r in daily_returns.items()}

    stats_returns = {stat().name: stat().calculate_from_returns(returns) for stat in RETURN_STATISTICS}
    stats_forecast = forecast_statistics(results[forecast_col], results.close, bars_per_day(timeframe), multiplier, cost_per_contract, horizon_bars=horizon)
    ordered = list(ordered_stats(stats_returns, {}, stats_forecast).items())
    turnover_at = [name for name, _ in ordered].index("Returns Volatility (252 days)") + 1
    ordered.insert(turnover_at, ("Turnover (round trips per day)", turnover(results.contracts)))
    stats = {"Total Net PnL": results.net_pnl.sum(), **dict(ordered)}

    return pd.Series({
        name: f"{float(value):,.0f}" if name == "Total Net PnL" else f"{float(value):,.4f}"
        for name, value in stats.items()
    })
