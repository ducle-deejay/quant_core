import numpy as np
import pandas as pd

from nautilus_bridge.analyzer.statistics import NANOS_PER_YEAR, TRADING_DAYS_PER_YEAR


def ic(signal, fwd_ret):
    return signal.corr(fwd_ret)


def ic_tstat(signal, fwd_ret, horizon):
    n_independent = pd.concat([signal, fwd_ret], axis=1).dropna().shape[0] / horizon
    return ic(signal, fwd_ret) * np.sqrt(n_independent)


def hit_rate(signal, fwd_ret):
    pair = pd.concat([np.sign(signal), np.sign(fwd_ret)], axis=1).dropna()
    pair = pair[(pair.iloc[:, 0] != 0) & (pair.iloc[:, 1] != 0)]
    return (pair.iloc[:, 0] == pair.iloc[:, 1]).mean()


def ic_ir(signal, fwd_ret, period):
    pair = pd.concat({"signal": signal, "fwd_ret": fwd_ret}, axis=1).dropna()
    ics = pair.groupby(pd.Grouper(freq=period)).apply(lambda g: g.signal.corr(g.fwd_ret)).dropna()
    return ics.mean() / ics.std()


def pool_corr(signal, pool):
    return pool.corrwith(signal)


def turnover(position):
    traded = position.diff().fillna(position).abs().sum()
    ts = position.index.asi8
    dt = np.diff(ts, append=ts[-1])
    avg_abs_position = (position.abs() * dt).sum() / dt.sum()
    years = dt.sum() / NANOS_PER_YEAR
    return traded / 2 / avg_abs_position / years / TRADING_DAYS_PER_YEAR
