"""Cross-cutting contracts for the live wiring phase (milestone 1).

Single contract file so the parallel workstreams (portfolio orchestration,
bridge strategy, risk overlay) integrate without interface drift. Types here
are plain data + protocols with NO Nautilus imports, so every module stays
testable in isolation.

Canon references (frozen design, docs/enhanced/):
- STG-1-CANONICAL-SIM  : uniform score -> position mapping
- STG-5-POSITION-CONSTRUCTION : vol targeting stack -> target position
- STG-6-TRADE-SCHEDULING : target vs current -> child orders
- STG-7-RISK-OVERLAY   : telemetry + expectations -> interventions
Milestone-1 fee model  : DEC-006 (scalar cost_per_side at reference price)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class HarnessParams:
    """Canonical harness parameters (Component 1) and milestone-1 cost model."""

    span: int = 8
    z_window: int = 480
    band: float = 0.35
    cap: float = 2.0
    # DEC-006: fee 1.461 + half-spread 0.333 + buffer 0.5 bp at reference
    # price 1,500 = 2.294 bp per side; scalar until the two-part model lands.
    cost_per_side: float = 0.000229
    bars_per_day: int = 240


@dataclass(frozen=True)
class PortfolioConfig:
    """Everything the portfolio orchestrator needs to emit one target.

    weights come from the research-side refit (Component 4); for milestone 1
    they are static per run, refreshed offline between paper sessions.
    """

    expressions: tuple[str, ...]
    weights: tuple[float, ...]
    harness: HarnessParams = field(default_factory=HarnessParams)
    vol_target: float = 0.1  # annualized vol target, fraction
    vol_floor: float | None = None
    capital_vnd: float = 100_000_000.0
    # entrade deposit ratio 5% (OBS-009/OBS-010); warning 3%, handling 2%.
    margin_rate: float = 0.05
    safety_factor: float = 0.5
    max_contracts: int = 10
    buffer_bars: int = 2000  # rolling bar buffer for vectorized scoring


@dataclass(frozen=True)
class TargetPosition:
    """The bridge contract: one decision per bar, in signed contracts."""

    ts: datetime
    target_contracts: int  # signed; 0 = flat
    z_target: float  # pre-rounding z-scale target (debug/telemetry)
    reason: str
    components: dict[str, float] = field(default_factory=dict)


class Portfolio(Protocol):
    """Orchestration side: bars in, one target out. Pure alpha_core calls."""

    def compute_target(
        self,
        bars: dict[str, list[float]],
        ts: datetime,
    ) -> TargetPosition: ...


@dataclass(frozen=True)
class RiskState:
    """Mirror of the canon Component 7 layer-3 ladder, minus shutdown."""

    status: str = "ACTIVE"  # ACTIVE | HALTED (soft halt) | REDUCING
    reason: str = ""


class RiskController(Protocol):
    """Risk side: gate every target before it becomes an order."""

    def gate(self, target: TargetPosition) -> tuple[bool, str]: ...

    def status(self) -> RiskState: ...
