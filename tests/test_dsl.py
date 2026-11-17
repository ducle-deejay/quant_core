import numpy as np
import pandas as pd
import pytest

from methodica.dsl import compute


@pytest.fixture
def bars():
    rng = np.random.default_rng(0)
    close = 1_000 + rng.normal(size=500).cumsum()
    return pd.DataFrame({"close": close, "volume": rng.integers(1, 100, size=500)})


def ema_cross(bars):
    close = bars.close
    fast = close.ewm(span=10, adjust=False, min_periods=10).mean()
    slow = close.ewm(span=20, adjust=False, min_periods=20).mean()
    price_std = close.diff().ewm(span=20, adjust=False, min_periods=20).std()
    return (fast - slow) / price_std


def test_expression_matches_hand_written_alpha(bars):
    result = compute("(ewma(close, 10) - ewma(close, 20)) / ewm_std(ts_delta(close, 1), 20)", bars)

    pd.testing.assert_series_equal(result, ema_cross(bars), check_exact=True)


@pytest.mark.parametrize(
    "expression",
    [
        "open",
        "unknown_op(close, 3)",
        "close.__class__",
        "ewma(close, span=10)",
        "close > 1",
        "close[0]",
        "'close'",
        "__import__('os')",
    ],
)
def test_rejects_expression_outside_whitelist(bars, expression):
    with pytest.raises(ValueError):
        compute(expression, bars)
