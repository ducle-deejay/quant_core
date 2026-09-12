"""Cross-role contracts: harness params, targets, risk decisions, configs.
Plain data + protocols with no Nautilus imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from .instruments import CostModel, Instrument

__all__ = [
    "Account",
    "AccountLimits",
    "CostModel",
    "HarnessParams",
    "Instrument",
    "Portfolio",
    "PortfolioConfig",
    "RiskAction",
    "RiskConfig",
    "RiskDecision",
    "RiskState",
    "TargetPosition",
]


class Account(StrEnum):
    """Trading account routing target (paper/demo vs live)."""

    DEMO = "demo"
    LIVE = "live"


@dataclass(frozen=True)
class HarnessParams:
    """Canonical harness parameters (Component 1).

    The per-side cost scalar moved to :class:`CostModel.cost_per_side_frac`.
    """

    span: int = 8
    z_window: int = 480
    band: float = 0.35
    cap: float = 2.0
    bars_per_day: int = 240


@dataclass(frozen=True)
class AccountLimits:
    """Account-level sizing limits shared by portfolio and risk."""

    capital_vnd: float = 100_000_000.0
    safety_factor: float = 0.5
    # entrade deposit ratio 5%; warning 3%, handling 2%.
    margin_rate: float = 0.05
    max_contracts: int = 10


@dataclass(frozen=True)
class PortfolioConfig:
    """Everything the portfolio orchestrator needs to emit one target.

    weights come from the research-side refit; per run they are static,
    refreshed offline between paper sessions.
    """

    expressions: tuple[str, ...]
    weights: tuple[float, ...]
    harness: HarnessParams = field(default_factory=HarnessParams)
    vol_target: float = 0.1  # annualized vol target, fraction
    vol_floor: float | None = None
    limits: AccountLimits = field(default_factory=AccountLimits)
    buffer_bars: int = 2000  # rolling bar buffer for vectorized scoring


@dataclass(frozen=True)
class RiskConfig:
    """Everything the risk overlay needs to approve one target.

    ``intraday_loss_limit`` is a fraction of capital (renamed from
    ``intraday_loss_pct``; fractions carry no suffix).
    """

    limits: AccountLimits = field(default_factory=AccountLimits)
    instrument: Instrument = field(default_factory=lambda: Instrument.load("VN30F1M"))
    intraday_loss_limit: float = 0.02  # fraction of capital
    staleness_secs: float = 60.0
    session_close_local_time: str = "14:00"
    tz: str = "Asia/Ho_Chi_Minh"
    flatten_max_attempts: int = 3
    flatten_retry_secs: float = 1.0


@dataclass(frozen=True)
class TargetPosition:
    """Portfolio's desired signed position for one decision timestamp.

    This is a request from the portfolio, not a risk approval, actual
    position, Nautilus order, or fill.  Risk may cap, block, or force-flat
    this desired target before execution.
    """

    ts: datetime
    target_contracts: int  # signed; 0 = flat
    z_target: float  # pre-rounding z-scale target (debug/telemetry)
    reason: str
    components: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ts, datetime)
            or self.ts.tzinfo is None
            or self.ts.utcoffset() is None
        ):
            raise ValueError("ts must be a timezone-aware datetime")
        if isinstance(self.target_contracts, bool) or not isinstance(
            self.target_contracts, int
        ):
            raise ValueError("target_contracts must be an integer")
        if isinstance(self.z_target, bool) or not isinstance(
            self.z_target, (int, float)
        ):
            raise ValueError("z_target must be a finite number")
        if not math.isfinite(self.z_target):
            raise ValueError("z_target must be a finite number")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")
        if not isinstance(self.components, dict):
            raise ValueError("components must be a dict")
        for name, value in self.components.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("component names must be non-empty strings")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"component {name!r} must be a finite number")
            if not math.isfinite(value):
                raise ValueError(f"component {name!r} must be a finite number")


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
    """Risk side: decide how a desired target may proceed."""

    def decide(self, target: TargetPosition) -> "RiskDecision": ...


RiskAction = Literal["approve", "cap", "block", "force-flat"]


@dataclass(frozen=True)
class RiskDecision:
    """Risk's decision for one portfolio desired target.

    ``approved_target_contracts`` is the target that execution may pursue;
    ``current_contracts`` is the actual signed position observed by the risk
    layer.  A blocked decision retains that actual position as its approved
    target.  A force-flat decision always approves zero.
    """

    desired: TargetPosition
    approved_target_contracts: int
    action: RiskAction
    reason: str
    current_contracts: int

    def __post_init__(self) -> None:
        if not isinstance(self.desired, TargetPosition):
            raise ValueError("desired must be a TargetPosition")
        if isinstance(self.approved_target_contracts, bool) or not isinstance(
            self.approved_target_contracts, int
        ):
            raise ValueError("approved_target_contracts must be an integer")
        if self.action not in ("approve", "cap", "block", "force-flat"):
            raise ValueError("action must be approve, cap, block, or force-flat")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")
        if isinstance(self.current_contracts, bool) or not isinstance(
            self.current_contracts, int
        ):
            raise ValueError("current_contracts must be an integer")
        if (
            self.action == "approve"
            and self.approved_target_contracts != self.desired.target_contracts
        ):
            raise ValueError("approve decisions must preserve the desired target")
        if self.action == "cap":
            desired = self.desired.target_contracts
            approved = self.approved_target_contracts
            if approved == desired:
                raise ValueError("cap decisions must change the desired target")
            if abs(approved) > abs(desired):
                raise ValueError("cap decisions cannot increase absolute target exposure")
            if desired != 0 and approved != 0 and (desired > 0) != (approved > 0):
                raise ValueError("cap decisions cannot reverse the desired target")
        if self.action == "force-flat" and self.approved_target_contracts != 0:
            raise ValueError("force-flat decisions must approve zero contracts")
        if (
            self.action == "block"
            and self.approved_target_contracts != self.current_contracts
        ):
            raise ValueError("blocked decisions must retain the actual current position")
