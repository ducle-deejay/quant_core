import pandas as pd

from methodica.alpha_evaluator.analyzer import alpha_metrics, analyze
from methodica.common.costs import cost_per_contract
from methodica.common.dataset import fit_mask, forward_return, load_bars, load_instrument, session_bars
from methodica.common.signals import raw_signals
from nautilus_bridge.backtest.sample_split import sample_window


def run_alpha_evaluator(*, instrument_id, alphas, commission, slippage=0.0, horizon=10, pool=None):
    multiplier = load_instrument(instrument_id).multiplier.as_double()
    cost = cost_per_contract(commission, slippage, multiplier)

    src = load_bars(instrument_id)
    bars = session_bars(src, "1-MINUTE")

    in_fit = fit_mask(bars.index, horizon)
    fwd_ret = forward_return(bars.close, horizon)[in_fit]
    pool_signals = raw_signals(pool, src, bars.index)[in_fit] if pool else None

    metrics = {}
    for name, expression in alphas.items():
        signal = raw_signals({name: expression}, src, bars.index)[name][in_fit]
        others = pool_signals.drop(columns=name, errors="ignore") if pool else None
        metrics[name] = alpha_metrics(signal, fwd_ret, bars.close, horizon, multiplier, cost, others)
    metrics = pd.DataFrame(metrics).T
    analyze(metrics, *sample_window("FIT"))
    return metrics
