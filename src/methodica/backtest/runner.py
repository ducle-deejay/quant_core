import numpy as np
import pandas as pd
from nautilus_trader.model import BarType
from nautilus_trader.model import Money

from methodica.backtest.analyzer import performance_statistics
from methodica.backtest.forecast import combination_weights, refine_forecast, standardize
from methodica.backtest.sizing import target_contracts, optimal_position
from methodica.common.costs import cost_per_contract
from methodica.common.dataset import fit_mask, forward_return, load_bars, load_instrument, session_bars
from methodica.common.signals import raw_signals
from nautilus_bridge.backtest.sample_split import sample_window
from nautilus_bridge.data.trading_days import LOOKBACK_TRADING_DAYS, warmup_start


def pnl_frame(contracts, close, multiplier, cost_per_contract):
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


def run_backtest(
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
    if sample not in ("IS", "OS"):
        raise ValueError(f"sample must be 'IS' or 'OS', got {sample!r}")

    source_bar_type = BarType.from_str(f"{instrument_id}-1-MINUTE-LAST-EXTERNAL")
    instrument = load_instrument(instrument_id)
    multiplier = instrument.multiplier.as_double()
    margin_init = float(instrument.margin_init) if margin_init is None else margin_init
    book_size = Money.from_str(book_size).as_double()
    cost = cost_per_contract(commission, slippage, multiplier)

    src = load_bars(instrument_id)
    bars = session_bars(src, timeframe)

    start, end = sample_window(sample)
    fit_start, fit_end = sample_window("FIT")
    signals = raw_signals(alphas, src, bars.index)
    standardized_signals = standardize(signals, fit_start, fit_end)
    fwd_ret = forward_return(bars.close, horizon)
    train = fit_mask(bars.index, horizon)
    weights = combination_weights(standardized_signals, fwd_ret, train)

    lookback_start = warmup_start(source_bar_type, start, LOOKBACK_TRADING_DAYS)
    bars = bars[(bars.index >= lookback_start) & (bars.index < end)]
    signals = signals.loc[bars.index]
    standardized_signals = standardized_signals.loc[bars.index]
    test = bars.index >= start

    vol = volatility_model(bars, timeframe, horizon)
    refined_forecast = refine_forecast(standardized_signals, weights, vol)
    position = optimal_position(refined_forecast, vol, risk_aversion)
    contracts = target_contracts(position, bars.close, book_size, multiplier, margin_init)
    contracts = trade_only_in_window(contracts, test)
    pnl = pnl_frame(contracts, bars.close, multiplier, cost)
    results = bars.join(signals).assign(vol=vol, refined_forecast=refined_forecast, position=position).join(pnl)[test]
    performance = performance_statistics(results, "refined_forecast", book_size, timeframe, horizon, multiplier, cost)
    return results, performance
