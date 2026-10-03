from __future__ import annotations

from collections import deque
from collections.abc import Callable
from collections.abc import Iterable
from datetime import date

import pandas as pd

from nautilus_bridge.alphas.frame import BinRow
from nautilus_bridge.alphas.frame import bins_frame
from nautilus_bridge.data.trading_days import trading_day

AlphaFn = Callable[[pd.DataFrame], pd.Series]


class PrecomputedSource:

    def __init__(self, exposure: pd.Series) -> None:
        self._exposure = exposure.to_dict()

    def warmup(self, bins: Iterable[BinRow]) -> None:
        pass

    def update(self, bin_row: BinRow) -> float | None:
        bin_end = bin_row[0]
        if bin_end not in self._exposure:
            raise KeyError(f"No precomputed exposure for bin_end={bin_end}")
        return _exposure_or_none(self._exposure[bin_end])


class RollingSource:

    def __init__(self, alpha_fn: AlphaFn, trading_days: int) -> None:
        self._alpha_fn = alpha_fn
        self._trading_days = trading_days
        self._bins: deque[BinRow] = deque()
        self._days: deque[date] = deque()

    def warmup(self, bins: Iterable[BinRow]) -> None:
        for bin_row in bins:
            self._append(bin_row)

    def update(self, bin_row: BinRow) -> float | None:
        self._append(bin_row)
        if len(self._days) < self._trading_days:
            return None
        return _exposure_or_none(self._alpha_fn(bins_frame(self._bins)).iloc[-1])

    def _append(self, bin_row: BinRow) -> None:
        day = trading_day(bin_row[0])
        if not self._days or day != self._days[-1]:
            self._days.append(day)
        self._bins.append(bin_row)
        while len(self._days) > self._trading_days:
            oldest = self._days.popleft()
            while trading_day(self._bins[0][0]) == oldest:
                self._bins.popleft()


AlphaSource = PrecomputedSource | RollingSource


def _exposure_or_none(value: float) -> float | None:
    return None if pd.isna(value) else float(value)
