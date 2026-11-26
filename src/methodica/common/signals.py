import pandas as pd

from methodica.common.dataset import session_bars
from methodica.dsl import compute


def raw_signals(alphas, src, index):
    minute_bars = session_bars(src, "1-MINUTE")
    signals = pd.DataFrame({name: compute(expression, minute_bars) for name, expression in alphas.items()})
    return signals.reindex(index, method="ffill")
