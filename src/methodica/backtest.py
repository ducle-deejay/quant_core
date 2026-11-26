import numpy as np
import pandas as pd
from nautilus_trader.analysis import (
    MaxDrawdown,
    ReturnsAverage,
    ReturnsVolatility,
    SharpeRatio,
)
from nautilus_trader.model import BarType
from nautilus_trader.model import Money
from nautilus_trader.persistence import ParquetDataCatalog

from methodica.dsl import compute
from nautilus_bridge.alphas.session_resampling import bar_row, bars_frame, bars_per_day, resample_by_session
from nautilus_bridge.analyzer.analyzer import ordered_stats
from nautilus_bridge.analyzer.forecast_statistics import forecast_statistics
from nautilus_bridge.analyzer.statistics import NANOS_PER_YEAR, TRADING_DAYS_PER_YEAR
from nautilus_bridge.backtest.sample_split import sample_window
from nautilus_bridge.data.catalog import catalog_path
from nautilus_bridge.data.trading_days import LOOKBACK_TRADING_DAYS, VN_TZ, warmup_start

BPS = 10_000

RETURN_STATISTICS = [SharpeRatio, ReturnsAverage, ReturnsVolatility, MaxDrawdown]


def forward_return(close, horizon):
    return close.pct_change(horizon).shift(-horizon)


def compute_raw_signals(alphas, src, index):
    minute_bars = resample_by_session(src, "1-MINUTE")
    signals = pd.DataFrame({name: compute(expression, minute_bars) for name, expression in alphas.items()})
    signals.index = pd.to_datetime(signals.index, unit="ns", utc=True).tz_convert(VN_TZ)
    return signals.reindex(index, method="ffill")


def standardize(signals, fit_start, fit_end):
    in_fit = (signals.index >= fit_start) & (signals.index < fit_end)
    mean, std = signals[in_fit].mean(), signals[in_fit].std()
    return (signals - mean) / std


def compute_combination_weights(standardized_signals, fwd_ret, train):
    ic = standardized_signals[train].corrwith(fwd_ret[train])
    rho = standardized_signals[train].corr()
    weights = pd.Series(np.linalg.solve(rho, ic), index=standardized_signals.columns)
    return weights, ic, rho


def refine_forecast(signals, weights, predicted_volatility):
    return predicted_volatility * (signals @ weights) * BPS


def optimal_position(alpha_bps, predicted_volatility, risk_aversion):
    return (alpha_bps / BPS) / (2 * risk_aversion * predicted_volatility ** 2)


def compute_target_contracts(position, close, book_size, multiplier, margin_init):
    max_contracts = np.floor(book_size / (close * multiplier * margin_init))
    return (
        np.trunc(position * book_size / (close * multiplier))
        .clip(-max_contracts, max_contracts)
        .fillna(0)
        + 0.0
    )


def compute_pnl(contracts, close, multiplier, cost_per_contract):
    traded_contracts = contracts.diff().fillna(contracts)
    pnl = contracts.shift(1) * close.diff() * multiplier + 0.0
    cost = traded_contracts.abs() * cost_per_contract
    return pd.DataFrame({
        "contracts": contracts,
        "traded_contracts": traded_contracts,
        "pnl": pnl,
        "cost": cost,
        "net_pnl": pnl - cost,
    })


def trade_only_in_window(contracts, test):
    contracts = contracts.where(test, 0.0)
    contracts.iloc[np.flatnonzero(test)[-1]] = 0.0
    return contracts


def turnover_daily(contracts):
    traded = contracts.diff().fillna(contracts).abs().sum()
    ts = contracts.index.asi8
    dt = np.diff(ts, append=ts[-1])
    avg_abs_contracts = (contracts.abs() * dt).sum() / dt.sum()
    years = dt.sum() / NANOS_PER_YEAR
    return traded / 2 / avg_abs_contracts / years / TRADING_DAYS_PER_YEAR


def compute_statistics(bars, forecast_col, book_size, timeframe, horizon, multiplier, cost_per_contract):
    equity = (book_size + bars.net_pnl.fillna(0).cumsum()).tz_convert("UTC")
    days = pd.date_range(equity.index[0].normalize(), equity.index[-1].normalize(), freq="D", tz="UTC")
    daily_returns = (
        equity.groupby(equity.index.normalize()).last()
        .reindex(days).ffill().fillna(book_size)
        .pct_change().fillna(0)
    )
    returns = {int(ts.value): r for ts, r in daily_returns.items()}

    stats_returns = {stat().name: stat().calculate_from_returns(returns) for stat in RETURN_STATISTICS}
    stats_forecast = forecast_statistics(bars[forecast_col], bars.close, bars_per_day(timeframe), multiplier, cost_per_contract, horizon_bars=horizon)
    ordered = list(ordered_stats(stats_returns, {}, stats_forecast).items())
    turnover_at = [name for name, _ in ordered].index("Returns Volatility (252 days)") + 1
    ordered.insert(turnover_at, ("Turnover (round trips per day)", turnover_daily(bars.contracts)))
    stats = {"Total Net PnL": bars.net_pnl.sum(), **dict(ordered)}

    return pd.Series({
        name: f"{float(value):,.0f}" if name == "Total Net PnL" else f"{float(value):,.4f}"
        for name, value in stats.items()
    })


def backtest(
    *,
    instrument_id,
    timeframe,
    alphas,
    sample="IS",
    horizon=10,
    book_size,
    commission,
    slippage=0.0,
    margin_init=None,
    volatility_model,
    risk_aversion,
):
    source_bar_type = BarType.from_str(f"{instrument_id}-1-MINUTE-LAST-EXTERNAL")
    catalog = ParquetDataCatalog(str(catalog_path()))
    instrument = catalog.instruments(instrument_ids=[instrument_id])[0]
    multiplier = instrument.multiplier.as_double()
    margin_init = float(instrument.margin_init) if margin_init is None else margin_init
    book_size = Money.from_str(book_size).as_double()
    commission = Money.from_str(commission).as_double()

    src = bars_frame(bar_row(bar) for bar in catalog.query_bars([str(source_bar_type)]))
    bars = resample_by_session(src, timeframe)
    bars.index = pd.to_datetime(bars.index, unit="ns", utc=True).tz_convert(VN_TZ)

    start, end = sample_window(sample)
    fit_start, fit_end = sample_window("FIT")
    raw_signals = compute_raw_signals(alphas, src, bars.index)
    standardized_signals = standardize(raw_signals, fit_start, fit_end)
    fwd_ret = forward_return(bars.close, horizon)
    realized_at = bars.index.to_series().shift(-horizon)
    train = ((bars.index >= fit_start) & (realized_at < fit_end)).to_numpy()
    weights, ic, rho = compute_combination_weights(standardized_signals, fwd_ret, train)
    in_fit = (bars.index >= fit_start) & (bars.index < fit_end)
    fit = {
        "data": (
            bars.join(raw_signals)
            .join(standardized_signals.add_prefix("standardized_"))
            .assign(forward_return=fwd_ret, train=train)[in_fit]
        ),
        "ic": ic,
        "rho": rho,
        "weights": weights,
    }

    lookback_start = warmup_start(source_bar_type, start, LOOKBACK_TRADING_DAYS)
    bars = bars[(bars.index >= lookback_start) & (bars.index < end)]
    raw_signals = raw_signals.loc[bars.index]
    standardized_signals = standardized_signals.loc[bars.index]
    test = bars.index >= start

    vol = volatility_model(bars, timeframe, horizon)
    alpha = refine_forecast(standardized_signals, weights, vol)
    position = optimal_position(alpha, vol, risk_aversion)
    contracts = compute_target_contracts(position, bars.close, book_size, multiplier, margin_init)
    contracts = trade_only_in_window(contracts, test)
    cost_per_contract = commission + slippage * multiplier
    pnl = compute_pnl(contracts, bars.close, multiplier, cost_per_contract)
    results = bars.join(raw_signals).assign(vol=vol, alpha=alpha, position=position).join(pnl)[test]
    performance = compute_statistics(results, "alpha", book_size, timeframe, horizon, multiplier, cost_per_contract)
    return results, performance, fit
