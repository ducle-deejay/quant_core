import numpy as np
import pandas as pd

from nautilus_bridge.alphas.session_resampling import bars_per_day


def ic(signal, fwd_ret):
    return signal.corr(fwd_ret)


def ic_tstat(signal, fwd_ret, horizon):
    """Overlapping forward returns leave about one independent observation per `horizon` bars."""
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


def autocorr_decay(signal, lags=range(1, bars_per_day("1-MINUTE") + 1)):
    return pd.Series({lag: signal.autocorr(lag) for lag in lags}, name="autocorrelation")


def pool_corr(signal, pool):
    return pool.corrwith(signal)
