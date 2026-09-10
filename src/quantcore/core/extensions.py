"""Small extension contracts used by the research and execution APIs.

These protocols describe the values already exchanged by the role modules.
They intentionally do not model Nautilus instruments, orders, or positions;
those objects remain owned by Nautilus at the live boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Protocol, Sequence, runtime_checkable

if TYPE_CHECKING:
    from quantcore.execution import ExecutionConfig


@runtime_checkable
class QuantitativeModel(Protocol):
    """Score close and volume observations into one finite-length series."""

    def score(self, close: Sequence[float], volume: Sequence[float]) -> list[float]: ...


@runtime_checkable
class PortfolioOptimizer(Protocol):
    """Combine per-alpha score series into one composite score series."""

    def optimize(self, scores: Sequence[Sequence[float]]) -> list[float]: ...


@runtime_checkable
class RiskMeasure(Protocol):
    """Transform score and volatility series using the configured risk model."""

    def adjust(
        self,
        z_scores: Sequence[float],
        vol_est: Sequence[float],
        target_vol: float,
        drawdowns: Sequence[float] | None = None,
        floor: float | None = None,
    ) -> list[float]: ...


@runtime_checkable
class ExecutionAlgorithm(Protocol):
    """Split a signed contract gap into ordered signed child quantities."""

    def plan(self, gap_contracts: int, config: "ExecutionConfig") -> list[int]: ...


class _CallableQuantitativeModel:
    """Narrow adapter for the existing ``fn(close, volume)`` registration API."""

    def __init__(self, fn: Callable[[Sequence[float], Sequence[float]], Iterable[float]]) -> None:
        self._fn = fn

    def score(self, close: Sequence[float], volume: Sequence[float]) -> list[float]:
        return list(self._fn(close, volume))

    def __call__(self, close: Sequence[float], volume: Sequence[float]) -> list[float]:
        return self.score(close, volume)


class _CallablePortfolioOptimizer:
    """Narrow adapter for existing ``fn(scores)`` functions."""

    def __init__(self, fn: Callable[..., Iterable[float]]) -> None:
        self._fn = fn

    def optimize(self, scores: Sequence[Sequence[float]]) -> list[float]:
        return list(self._fn(scores))

    def __call__(
        self,
        scores: Sequence[Sequence[float]],
    ) -> list[float]:
        return self.optimize(scores)


class _CallableRiskMeasure:
    """Narrow adapter for the existing sizing function signature."""

    def __init__(self, fn: Callable[..., Iterable[float]]) -> None:
        self._fn = fn

    def adjust(
        self,
        z_scores: Sequence[float],
        vol_est: Sequence[float],
        target_vol: float,
        drawdowns: Sequence[float] | None = None,
        floor: float | None = None,
    ) -> list[float]:
        return list(self._fn(z_scores, vol_est, target_vol, drawdowns, floor))

    def __call__(
        self,
        z_scores: Sequence[float],
        vol_est: Sequence[float],
        target_vol: float,
        drawdowns: Sequence[float] | None = None,
        floor: float | None = None,
    ) -> list[float]:
        return self.adjust(z_scores, vol_est, target_vol, drawdowns, floor)


class _CallableExecutionAlgorithm:
    """Narrow adapter for the existing ``fn(gap, config)`` plan functions."""

    def __init__(self, fn: Callable[..., Iterable[int]]) -> None:
        self._fn = fn

    def plan(self, gap_contracts: int, config: "ExecutionConfig") -> list[int]:
        return list(self._fn(gap_contracts, config))

    def __call__(self, gap_contracts: int, config: "ExecutionConfig") -> list[int]:
        return self.plan(gap_contracts, config)
