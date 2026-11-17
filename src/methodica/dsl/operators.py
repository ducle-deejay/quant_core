def ts_delta(x, d):
    return x.diff(d)


def ts_mean(x, w):
    return x.rolling(w).mean()


def ts_std(x, w):
    return x.rolling(w).std()


def ts_min(x, w):
    return x.rolling(w).min()


def ts_max(x, w):
    return x.rolling(w).max()


def ts_corr(x, y, w):
    return x.rolling(w).corr(y)


def ewma(x, span):
    return x.ewm(span=span, adjust=False, min_periods=span).mean()


def ewm_std(x, span):
    return x.ewm(span=span, adjust=False, min_periods=span).std()


def absolute(x):
    return x.abs()


OPERATORS = {
    "ts_delta": ts_delta,
    "ts_mean": ts_mean,
    "ts_std": ts_std,
    "ts_min": ts_min,
    "ts_max": ts_max,
    "ts_corr": ts_corr,
    "ewma": ewma,
    "ewm_std": ewm_std,
    "abs": absolute,
}
