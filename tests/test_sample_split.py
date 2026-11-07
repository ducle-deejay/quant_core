from __future__ import annotations

import pandas as pd
import pytest

from nautilus_bridge.backtest.sample_split import backtest_period


def test_backtest_period_keeps_bounds_inside_the_data() -> None:
    period = backtest_period(
        start="2021-01-01",
        end="2024-01-01",
        data_start=pd.Timestamp("2020-01-01", tz="UTC"),
        data_end=pd.Timestamp("2025-01-01", tz="UTC"),
    )
    assert period == (pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC"))


def test_backtest_period_narrows_bounds_outside_the_data() -> None:
    period = backtest_period(
        start="2019-01-01",
        end="2026-01-01",
        data_start=pd.Timestamp("2020-01-01", tz="UTC"),
        data_end=pd.Timestamp("2025-01-01", tz="UTC"),
    )
    assert period == (pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC"))


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2022-01-01", "2022"),
        ("2023-01-01", "2022-01-01"),
        ("2026-01-01", "2027-01-01"),
    ],
)
def test_backtest_period_rejects_end_not_after_start(start: str, end: str) -> None:
    with pytest.raises(ValueError, match="must be after start"):
        backtest_period(
            start=start,
            end=end,
            data_start=pd.Timestamp("2020-01-01", tz="UTC"),
            data_end=pd.Timestamp("2025-01-01", tz="UTC"),
        )
