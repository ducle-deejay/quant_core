import numpy as np
from tabulate import tabulate

from methodica.common.metrics import hit_rate, ic, ic_ir, ic_tstat, pool_corr, turnover
from methodica.common.signals import orthogonalize
from nautilus_bridge.alphas.session_resampling import bars_per_day
from nautilus_bridge.analyzer.forecast_statistics import forecast_statistics


def alpha_metrics(signal, fwd_ret, close, horizon, multiplier, cost_per_contract, pool=None):
    z = (signal - signal.mean()) / signal.std()
    oriented = (z * np.sign(ic(signal, fwd_ret))).reindex(close.index)
    net = forecast_statistics(oriented, close, bars_per_day("1-MINUTE"), multiplier, cost_per_contract, horizon_bars=horizon)
    metrics = {
        "IC": ic(signal, fwd_ret),
        "t-stat": ic_tstat(signal, fwd_ret, horizon),
        "Hit rate": hit_rate(signal, fwd_ret),
        "ICIR": ic_ir(signal, fwd_ret),
        "Turnover": turnover(z),
        "Net Sharpe": next(value for key, value in net.items() if key.startswith("Sharpe Ratio (IC-based")),
    }
    if pool is not None:
        residual = orthogonalize(signal, pool)
        corr = pool_corr(signal, pool).abs()
        metrics |= {
            "Residual IC": ic(residual, fwd_ret),
            "Residual t-stat": ic_tstat(residual, fwd_ret, horizon),
            "Max corr": corr.max(),
            "Closest alpha": corr.idxmax(),
        }
    return metrics


def render_metrics(metrics):
    print(tabulate(metrics, headers="keys", tablefmt="fancy_grid", floatfmt=".4f"))


def analyze(metrics, fit_start, fit_end):
    print(f"\nPeriod: FIT ({fit_start.date()} → {fit_end.date()})\n")
    render_metrics(metrics)
