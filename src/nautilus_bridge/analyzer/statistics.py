from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from nautilus_trader.analysis import PortfolioStatistic
from nautilus_trader.model import OrderSide
from nautilus_trader.model import Position
from nautilus_trader.portfolio import Portfolio

NANOS_PER_YEAR = pd.Timedelta(days=365.25).value
TRADING_DAYS_PER_YEAR = 252


def round_trips_per_year(positions: Sequence[Position], start: int, end: int) -> float | None:
    """Round trips of the time-weighted average absolute position per year; None if never held."""
    fills = sorted(
        (fill.ts_event, float(fill.last_qty) if fill.order_side == OrderSide.BUY else -float(fill.last_qty))
        for position in positions
        for fill in position.events()
    )
    if not fills:
        return None

    traded = sum(abs(qty) for _, qty in fills)
    net_position = 0.0
    abs_position_time = 0.0
    last_ts = start
    for ts, qty in fills:
        abs_position_time += abs(net_position) * (ts - last_ts)
        net_position += qty
        last_ts = ts
    abs_position_time += abs(net_position) * (end - last_ts)

    period = end - start
    avg_abs_position = abs_position_time / period
    if avg_abs_position == 0:
        return None
    return (traded / 2) / avg_abs_position / (period / NANOS_PER_YEAR)


class Turnover(PortfolioStatistic):
    NAME = "Turnover (round trips per year)"

    def __init__(self, start: pd.Timestamp, end: pd.Timestamp) -> None:
        self._start = start.value
        self._end = end.value

    @property
    def name(self) -> str:
        return self.NAME

    def calculate_from_positions(self, positions: Sequence[Position]) -> float | None:
        return round_trips_per_year(positions, self._start, self._end)


class HoldingPeriod(PortfolioStatistic):
    NAME = "Holding Period (trading days)"

    def __init__(self, start: pd.Timestamp, end: pd.Timestamp) -> None:
        self._start = start.value
        self._end = end.value

    @property
    def name(self) -> str:
        return self.NAME

    def calculate_from_positions(self, positions: Sequence[Position]) -> float | None:
        turnover = round_trips_per_year(positions, self._start, self._end)
        if not turnover:
            return None
        return TRADING_DAYS_PER_YEAR / turnover


def register_statistics(portfolio: Portfolio, start: pd.Timestamp, end: pd.Timestamp) -> None:
    portfolio.register_statistic(Turnover(start, end))
    portfolio.register_statistic(HoldingPeriod(start, end))
