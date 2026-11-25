from __future__ import annotations

import pandas as pd
import pytest

from nautilus_bridge.backtest.sample_split import backtest_period
from nautilus_bridge.backtest.sample_split import sample_window


def test_samples_are_contiguous_and_do_not_overlap() -> None:
    cutoff_day = pd.Timestamp("2026-11-24", tz="UTC")
    fit_start, fit_end = sample_window("FIT", cutoff_day)
    is_start, is_end = sample_window("IS", cutoff_day)
    os_start, os_end = sample_window("OS", cutoff_day)

    assert fit_start < fit_end == is_start < is_end == os_start < os_end == cutoff_day


def test_backtest_period_without_end_stops_at_the_is_window_end() -> None:
    _, is_end = sample_window("IS")
    period = backtest_period(
        start="2020-01-01",
        sample="IS",
        data_start=pd.Timestamp("2020-01-01", tz="UTC"),
        data_end=is_end + pd.DateOffset(years=1),
    )
    assert period == (pd.Timestamp("2020-01-01", tz="UTC"), is_end)


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
