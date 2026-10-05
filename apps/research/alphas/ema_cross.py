from __future__ import annotations

import numpy as np
import pandas as pd

FAST_PERIOD = 10
SLOW_PERIOD = 20


def alpha(bars: pd.DataFrame) -> pd.Series:
    close = bars["close"]
    fast = close.ewm(span=FAST_PERIOD, adjust=False).mean()
    slow = close.ewm(span=SLOW_PERIOD, adjust=False).mean()

    forecast = pd.Series(np.where(fast >= slow, 1.0, -1.0), index=bars.index)
    forecast.iloc[: SLOW_PERIOD - 1] = np.nan
    return forecast
