from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nautilus_bridge.alphas.session_resampling import BAR_COLUMNS
from nautilus_bridge.alphas.session_resampling import SessionResampler
from nautilus_bridge.alphas.session_resampling import resample_by_session
from nautilus_bridge.alphas.session_resampling import session_bar_end
from nautilus_bridge.alphas.loader import load_alpha
from nautilus_bridge.alphas.forecast_runtime import PrecomputedForecast
from nautilus_bridge.alphas.forecast_runtime import RollingForecast

ema_cross = load_alpha(str(Path(__file__).parents[1] / "apps/research/alphas/ema_cross.py"))

TZ = "Asia/Ho_Chi_Minh"
LOOKBACK_DAYS = 10
TARGET_BARS_PER_DAY_30M = 9


def _local_ns(text: str) -> int:
    return pd.Timestamp(text, tz=TZ).value


def _minute_bars(days: list[str], drop: set[str] = frozenset(), seed: int = 7) -> pd.DataFrame:
    minutes = [
        *pd.date_range("09:01", "11:30", freq="1min").strftime("%H:%M"),
        *pd.date_range("13:01", "14:30", freq="1min").strftime("%H:%M"),
    ]
    ts_init = [
        _local_ns(f"{day} {hm}")
        for day in days
        for hm in [*minutes, "14:45"]
        if f"{day} {hm}" not in drop
    ]
    ts_init = np.array(ts_init, dtype=np.int64)
    is_auction = pd.to_datetime(ts_init, utc=True).tz_convert(TZ).strftime("%H:%M") == "14:45"
    ts_event = np.where(is_auction, ts_init, ts_init - 60_000_000_000)
    close = 1_000 + np.random.default_rng(seed).normal(0, 1, len(ts_init)).cumsum()
    frame = pd.DataFrame(
        {
            "ts_init": ts_init,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1.0,
        },
        index=pd.Index(ts_event, name="ts_event"),
    )
    return frame[["ts_init", *BAR_COLUMNS]]


def _trading_days(n: int) -> list[str]:
    return [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2026-01-05", periods=n)]


@pytest.mark.parametrize(
    ("ts_init", "timeframe", "expected"),
    [
        ("09:01", "30-MINUTE", "09:30"),
        ("09:30", "30-MINUTE", "09:30"),
        ("09:31", "30-MINUTE", "10:00"),
        ("11:30", "30-MINUTE", "11:30"),
        ("13:01", "30-MINUTE", "13:30"),
        ("14:30", "30-MINUTE", "14:30"),
        ("14:45", "30-MINUTE", "14:45"),
        ("10:31", "1-HOUR", "11:00"),
        ("11:16", "1-HOUR", "11:30"),
        ("14:01", "1-HOUR", "14:30"),
    ],
)
def test_session_bar_end_anchors_target_bars_at_session_open(ts_init, timeframe, expected):
    bar_end = session_bar_end(
        np.array([_local_ns(f"2026-01-05 {ts_init}")]),
        timeframe,
    )
    assert bar_end[0] == _local_ns(f"2026-01-05 {expected}")


@pytest.mark.parametrize("ts_init", ["09:00", "12:00", "14:31", "15:00"])
def test_session_bar_end_rejects_bars_outside_sessions(ts_init):
    with pytest.raises(ValueError):
        session_bar_end(np.array([_local_ns(f"2026-01-05 {ts_init}")]), "30-MINUTE")


@pytest.mark.parametrize(
    "timeframe",
    [
        "1-MINUTE", "2-MINUTE", "3-MINUTE", "5-MINUTE", "10-MINUTE", "15-MINUTE", "20-MINUTE",
        "30-MINUTE", "1-HOUR", "2-HOUR", "4-HOUR",
    ],
)
def test_session_resampler_matches_resample_by_session(timeframe):
    days = _trading_days(3)
    drop = {f"{days[0]} 09:30", f"{days[0]} 10:12", f"{days[1]} 11:30", f"{days[2]} 14:30"}
    bars = _minute_bars(days, drop)

    resampler = SessionResampler(timeframe)
    streamed = [
        target_bar
        for row in bars.reset_index().itertuples(index=False, name=None)
        for target_bar in resampler.update(row)
    ]
    expected = resample_by_session(bars, timeframe)

    assert [row[0] for row in streamed] == expected.index.tolist()
    assert np.allclose([row[1:] for row in streamed], expected.to_numpy())


def test_alpha_value_at_each_target_bar_ignores_later_target_bars():
    target_bars = resample_by_session(_minute_bars(_trading_days(40)), "30-MINUTE")
    full = ema_cross(target_bars)
    for k in np.random.default_rng(0).integers(LOOKBACK_DAYS * TARGET_BARS_PER_DAY_30M, len(target_bars), 50):
        truncated = ema_cross(target_bars.iloc[: k + 1]).iloc[-1]
        assert truncated == full.iloc[k] or (np.isnan(truncated) and np.isnan(full.iloc[k]))


def test_rolling_forecast_matches_precomputed_forecast():
    target_bars = resample_by_session(_minute_bars(_trading_days(40)), "30-MINUTE")
    precomputed = PrecomputedForecast(ema_cross(target_bars))
    rolling = RollingForecast(ema_cross, LOOKBACK_DAYS)

    compared = 0
    for target_bar in target_bars.itertuples(name=None):
        expected = precomputed.update(target_bar)
        actual = rolling.update(target_bar)
        if actual is None or expected is None:
            continue
        assert actual == expected, f"bar_end={target_bar[0]}"
        compared += 1
    assert compared == len(target_bars) - (LOOKBACK_DAYS - 1) * TARGET_BARS_PER_DAY_30M
