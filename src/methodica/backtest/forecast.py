import numpy as np
import pandas as pd

BPS = 10_000


def standardize(signals, fit_start, fit_end):
    in_fit = (signals.index >= fit_start) & (signals.index < fit_end)
    mean, std = signals[in_fit].mean(), signals[in_fit].std()
    return (signals - mean) / std


def combination_weights(standardized_signals, fwd_ret, train):
    ic = standardized_signals[train].corrwith(fwd_ret[train])
    rho = standardized_signals[train].corr()
    return pd.Series(np.linalg.solve(rho, ic), index=standardized_signals.columns)


def refine_forecast(signals, weights, predicted_volatility):
    return predicted_volatility * (signals @ weights) * BPS
