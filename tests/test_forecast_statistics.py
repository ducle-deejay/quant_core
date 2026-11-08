from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nautilus_bridge.analyzer.forecast_statistics import forecast_statistics


@pytest.mark.parametrize("horizon_bars", [1, 3])
def test_ic_pairs_forecast_with_the_return_after_it(horizon_bars: int) -> None:
    close = pd.Series(1000 + np.random.default_rng(7).normal(size=500).cumsum())
    forward_return = close.shift(-horizon_bars) / close - 1
    backward_return = close / close.shift(horizon_bars) - 1

    ic_name = f"IC (Pearson, {horizon_bars} bar)"
    contract = {"bars_per_day": 9, "multiplier": 100_000, "commission_per_contract": 22_750}
    forward_ic = forecast_statistics(forward_return, close, **contract, horizon_bars=horizon_bars)[ic_name]
    backward_ic = forecast_statistics(backward_return, close, **contract, horizon_bars=horizon_bars)[ic_name]

    assert forward_ic == pytest.approx(1.0)
    assert abs(backward_ic) < 0.5
