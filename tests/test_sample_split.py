from __future__ import annotations

import pandas as pd
import pytest

from nautilus_bridge.backtest.sample_split import backtest_period


def test_backtest_period_returns_explicit_bounds() -> None:
    start, end = backtest_period(start="2026-01-01", end="2026-05-07")
    assert start == pd.Timestamp("2026-01-01", tz="UTC")
    assert end == pd.Timestamp("2026-05-07", tz="UTC")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-01-01", "2026"),
        ("2026-05-07", "2026-01-01"),
    ],
)
def test_backtest_period_rejects_end_not_after_start(start: str, end: str) -> None:
    with pytest.raises(ValueError, match="must be after start"):
        backtest_period(start=start, end=end)
