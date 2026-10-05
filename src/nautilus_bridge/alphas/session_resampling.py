from __future__ import annotations

from collections.abc import Iterable
from datetime import time

import numpy as np
import pandas as pd

from nautilus_trader.model import Bar
from nautilus_trader.model import BarAggregation
from nautilus_trader.model import BarSpecification

from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1M_SESSIONS
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import TradingSessions

BAR_COLUMNS = ("open", "high", "low", "close", "volume")

BarRow = tuple[int, int, float, float, float, float, float]
TargetBarRow = tuple[int, float, float, float, float, float]

MINUTE_NS = 60_000_000_000


def bar_row(bar: Bar) -> BarRow:
    return (
        bar.ts_event,
        bar.ts_init,
        bar.open.as_double(),
        bar.high.as_double(),
        bar.low.as_double(),
        bar.close.as_double(),
        bar.volume.as_double(),
    )


def bars_frame(rows: Iterable[BarRow]) -> pd.DataFrame:
    columns = ["ts_event", "ts_init", *BAR_COLUMNS]
    return pd.DataFrame(list(rows), columns=columns).set_index("ts_event")


def target_bars_frame(rows: Iterable[TargetBarRow]) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=["bar_end", *BAR_COLUMNS]).set_index("bar_end")


def session_bar_end(
    ts_init: np.ndarray,
    timeframe: str,
    sessions: TradingSessions = VN30F1M_SESSIONS,
) -> np.ndarray:
    return _session_bar_end(ts_init, _parse_timeframe(timeframe), sessions)


def resample_by_session(bars: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    bars = bars.sort_values("ts_init", kind="stable")
    bar_end = pd.Index(
        _session_bar_end(bars["ts_init"].to_numpy(), _parse_timeframe(timeframe), VN30F1M_SESSIONS),
        name="bar_end",
    )
    return bars.groupby(bar_end, sort=True).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"},
    )


class SessionResampler:

    def __init__(
        self,
        timeframe: str,
        sessions: TradingSessions = VN30F1M_SESSIONS,
    ) -> None:
        self._timeframe = _parse_timeframe(timeframe)
        self._sessions = sessions
        self._day_bounds: tuple[int, int] | None = None
        self._day_bar_ends: dict[int, int] = {}
        self._last_ts_init: int | None = None
        self._bar_end: int | None = None
        self._ohlcv: list[float] | None = None

    def update(self, row: BarRow) -> list[TargetBarRow]:
        ts_init = row[1]
        if self._last_ts_init is not None and ts_init <= self._last_ts_init:
            return []
        self._last_ts_init = ts_init

        bar_end = self._bar_end_of(ts_init)
        closed = []
        if self._bar_end is not None and bar_end != self._bar_end:
            closed.append(self._close())

        open_, high, low, close, volume = row[2:]
        if self._ohlcv is None:
            self._bar_end = bar_end
            self._ohlcv = [open_, high, low, close, volume]
        else:
            self._ohlcv[1] = max(self._ohlcv[1], high)
            self._ohlcv[2] = min(self._ohlcv[2], low)
            self._ohlcv[3] = close
            self._ohlcv[4] += volume

        if ts_init == bar_end:
            closed.append(self._close())
        return closed

    def _bar_end_of(self, ts_init: int) -> int:
        if self._day_bounds is None or not self._day_bounds[0] <= ts_init < self._day_bounds[1]:
            self._load_day(ts_init)
        bar_end = self._day_bar_ends.get(ts_init)
        if bar_end is None:
            ts = np.array([ts_init], dtype=np.int64)
            day_start = np.array([self._day_bounds[0]], dtype=np.int64)
            bar_end = int(_bar_end(ts, day_start, self._timeframe, self._sessions)[0])
        return bar_end

    def _load_day(self, ts_init: int) -> None:
        day_start = int(_local_day_start(np.array([ts_init]), self._sessions)[0])
        next_day = pd.Timestamp(day_start, tz="UTC").tz_convert(self._sessions.timezone) + pd.Timedelta(days=1)
        self._day_bounds = (day_start, next_day.normalize().value)

        minutes = np.arange(day_start + MINUTE_NS, self._day_bounds[1] + 1, MINUTE_NS, dtype=np.int64)
        day_starts = np.full(minutes.shape, day_start, dtype=np.int64)
        bar_ends = _session_bar_end_or_missing(minutes, day_starts, self._timeframe, self._sessions)
        inside = bar_ends >= 0
        self._day_bar_ends = dict(zip(minutes[inside].tolist(), bar_ends[inside].tolist()))

    def _close(self) -> TargetBarRow:
        row = (self._bar_end, *self._ohlcv)
        self._bar_end = None
        self._ohlcv = None
        return row


def _parse_timeframe(timeframe: str) -> pd.Timedelta:
    spec = BarSpecification.from_str(f"{timeframe}-LAST")
    if spec.aggregation not in (BarAggregation.MINUTE, BarAggregation.HOUR):
        raise ValueError(f"Session resampling supports MINUTE or HOUR timeframes, got {timeframe}")
    return pd.Timedelta(spec.timedelta)


def _session_bar_end(
    ts_init: np.ndarray,
    timeframe: pd.Timedelta,
    sessions: TradingSessions,
) -> np.ndarray:
    ts_init = np.asarray(ts_init, dtype=np.int64)
    return _bar_end(ts_init, _local_day_start(ts_init, sessions), timeframe, sessions)


def _local_day_start(ts_init: np.ndarray, sessions: TradingSessions) -> np.ndarray:
    local = pd.DatetimeIndex(pd.to_datetime(ts_init, unit="ns", utc=True)).tz_convert(sessions.timezone)
    return local.normalize().tz_convert("UTC").as_unit("ns").asi8


def _bar_end(
    ts_init: np.ndarray,
    day_start: np.ndarray,
    timeframe: pd.Timedelta,
    sessions: TradingSessions,
) -> np.ndarray:
    bar_end = _session_bar_end_or_missing(ts_init, day_start, timeframe, sessions)
    outside = bar_end < 0
    if outside.any():
        first = pd.Timestamp(int(ts_init[outside][0]), tz="UTC").tz_convert(sessions.timezone)
        raise ValueError(f"Bar with ts_init {first} is outside the trading sessions")
    return bar_end


def _session_bar_end_or_missing(
    ts_init: np.ndarray,
    day_start: np.ndarray,
    timeframe: pd.Timedelta,
    sessions: TradingSessions,
) -> np.ndarray:
    since_midnight = ts_init - day_start
    step = timeframe.value

    bar_end = np.full(ts_init.shape, -1, dtype=np.int64)
    for start, end in sessions.continuous:
        start_ns, end_ns = _time_ns(start), _time_ns(end)
        inside = (since_midnight > start_ns) & (since_midnight <= end_ns)
        steps = -((start_ns - since_midnight[inside]) // step)
        bar_end[inside] = day_start[inside] + np.minimum(start_ns + steps * step, end_ns)
    auction = since_midnight == _time_ns(sessions.closing_auction)
    bar_end[auction] = ts_init[auction]
    return bar_end


def _time_ns(value: time) -> int:
    return (value.hour * 60 + value.minute) * MINUTE_NS
