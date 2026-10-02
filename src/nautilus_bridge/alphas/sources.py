from __future__ import annotations

from collections import deque
from collections.abc import Callable
from collections.abc import Iterable

import pandas as pd

from nautilus_bridge.alphas.frame import BinRow
from nautilus_bridge.alphas.frame import bins_frame

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

    def __init__(self, alpha_fn: AlphaFn, window: int) -> None:
        self._alpha_fn = alpha_fn
        self._bins: deque[BinRow] = deque(maxlen=window)

    def warmup(self, bins: Iterable[BinRow]) -> None:
        self._bins.extend(bins)

    def update(self, bin_row: BinRow) -> float | None:
        self._bins.append(bin_row)
        if len(self._bins) < self._bins.maxlen:
            return None
        return _exposure_or_none(self._alpha_fn(bins_frame(self._bins)).iloc[-1])


AlphaSource = PrecomputedSource | RollingSource


def _exposure_or_none(value: float) -> float | None:
    return None if pd.isna(value) else float(value)
