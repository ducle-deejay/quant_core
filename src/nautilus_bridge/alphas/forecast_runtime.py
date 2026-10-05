from __future__ import annotations

from collections import deque
from collections.abc import Callable
from collections.abc import Iterable
from datetime import date

import pandas as pd

from nautilus_bridge.alphas.session_resampling import TargetBarRow
from nautilus_bridge.alphas.session_resampling import target_bars_frame
from nautilus_bridge.data.trading_days import trading_day

AlphaFn = Callable[[pd.DataFrame], pd.Series]


class PrecomputedForecast:

    def __init__(self, forecast: pd.Series) -> None:
        self._forecast = forecast.to_dict()

    def warmup(self, target_bars: Iterable[TargetBarRow]) -> None:
        pass

    def update(self, target_bar: TargetBarRow) -> float | None:
        bar_end = target_bar[0]
        if bar_end not in self._forecast:
            raise KeyError(f"No precomputed forecast for bar_end={bar_end}")
        return _forecast_or_none(self._forecast[bar_end])


class RollingForecast:

    def __init__(self, alpha_fn: AlphaFn, trading_days: int) -> None:
        self._alpha_fn = alpha_fn
        self._trading_days = trading_days
        self._target_bars: deque[TargetBarRow] = deque()
        self._days: deque[date] = deque()

    def warmup(self, target_bars: Iterable[TargetBarRow]) -> None:
        for target_bar in target_bars:
            self._append(target_bar)

    def update(self, target_bar: TargetBarRow) -> float | None:
        self._append(target_bar)
        if len(self._days) < self._trading_days:
            return None
        return _forecast_or_none(self._alpha_fn(target_bars_frame(self._target_bars)).iloc[-1])

    def _append(self, target_bar: TargetBarRow) -> None:
        day = trading_day(target_bar[0])
        if not self._days or day != self._days[-1]:
            self._days.append(day)
        self._target_bars.append(target_bar)
        while len(self._days) > self._trading_days:
            oldest = self._days.popleft()
            while trading_day(self._target_bars[0][0]) == oldest:
                self._target_bars.popleft()


ForecastRuntime = PrecomputedForecast | RollingForecast


def _forecast_or_none(value: float) -> float | None:
    return None if pd.isna(value) else float(value)
