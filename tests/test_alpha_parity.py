from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nautilus_bridge.alphas.ema_cross import ema_cross
from nautilus_bridge.alphas.frame import BAR_COLUMNS
from nautilus_bridge.alphas.frame import SessionBinner
from nautilus_bridge.alphas.frame import resample_session
from nautilus_bridge.alphas.frame import session_bin_end
from nautilus_bridge.alphas.sources import PrecomputedSource
from nautilus_bridge.alphas.sources import RollingSource

TZ = "Asia/Ho_Chi_Minh"
WINDOW = 120


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
    ("ts_init", "minutes", "expected"),
    [
        ("09:01", 30, "09:30"),
        ("09:30", 30, "09:30"),
        ("09:31", 30, "10:00"),
        ("11:30", 30, "11:30"),
        ("13:01", 30, "13:30"),
        ("14:30", 30, "14:30"),
        ("14:45", 30, "14:45"),
        ("11:16", 45, "11:30"),
        ("10:31", 45, "11:15"),
        ("13:46", 45, "14:30"),
    ],
)
def test_session_bin_end_anchors_bins_at_session_open(ts_init, minutes, expected):
    bin_end = session_bin_end(
        np.array([_local_ns(f"2026-01-05 {ts_init}")]),
        pd.Timedelta(minutes=minutes),
    )
    assert bin_end[0] == _local_ns(f"2026-01-05 {expected}")


@pytest.mark.parametrize("ts_init", ["09:00", "12:00", "14:31", "15:00"])
def test_session_bin_end_rejects_bars_outside_sessions(ts_init):
    with pytest.raises(ValueError):
        session_bin_end(np.array([_local_ns(f"2026-01-05 {ts_init}")]), pd.Timedelta(minutes=30))


@pytest.mark.parametrize("minutes", [1, 2, 3, 5, 7, 10, 15, 20, 30, 45, 60, 90, 120, 240])
def test_session_binner_matches_resample_session(minutes):
    days = _trading_days(3)
    drop = {f"{days[0]} 09:30", f"{days[0]} 10:12", f"{days[1]} 11:30", f"{days[2]} 14:30"}
    bars = _minute_bars(days, drop)
    timeframe = pd.Timedelta(minutes=minutes)

    binner = SessionBinner(timeframe)
    streamed = [
        bin_row
        for row in bars.reset_index().itertuples(index=False, name=None)
        for bin_row in binner.update(row)
    ]
    expected = resample_session(bars, timeframe)

    assert [row[0] for row in streamed] == expected.index.tolist()
    assert np.allclose([row[1:] for row in streamed], expected.to_numpy())


def test_alpha_value_at_each_bin_ignores_later_bins():
    bins = resample_session(_minute_bars(_trading_days(40)), pd.Timedelta(minutes=30))
    full = ema_cross(bins)
    for k in np.random.default_rng(0).integers(WINDOW, len(bins), 50):
        truncated = ema_cross(bins.iloc[: k + 1]).iloc[-1]
        assert truncated == full.iloc[k] or (np.isnan(truncated) and np.isnan(full.iloc[k]))


def test_rolling_source_matches_precomputed_source():
    bins = resample_session(_minute_bars(_trading_days(40)), pd.Timedelta(minutes=30))
    precomputed = PrecomputedSource(ema_cross(bins))
    rolling = RollingSource(ema_cross, WINDOW)

    compared = 0
    for bin_row in bins.itertuples(name=None):
        expected = precomputed.update(bin_row)
        actual = rolling.update(bin_row)
        if actual is None or expected is None:
            continue
        assert actual == expected, f"bin_end={bin_row[0]}"
        compared += 1
    assert compared == len(bins) - WINDOW + 1
