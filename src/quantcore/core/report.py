"""Researcher-facing report objects (DEC-017).

Reports stay in-memory; ``to_json`` is an explicit, on-demand export - the
API never auto-saves reports (only handoff artifacts are auto-saved).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class TearSheet:
    """Evaluation report for one alpha (Component 1 + Component 2 output)."""

    alpha_id: str
    dsl: str
    metrics: dict  # sharpe, max drawdown, IC ladder, walk-forward, cost drag, ...
    verdict: str  # "IN" | "OUT"
    reasons: tuple[str, ...] = ()
    provenance: dict = field(default_factory=dict)  # method/config versions
    generated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        return d

    def to_json(self, path: str | Path) -> Path:
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n")
        return p


@dataclass(frozen=True)
class SpecSheet:
    """Component 2 PASS artifact: expectations consumed by portfolio
    (capacity, expected Sharpe, holding period), risk (divergence gauges)
    and the live kill criteria."""

    alpha_id: str
    expected_holding_period_bars: int
    expected_net_sharpe: float
    capacity_contracts: int
    regime_notes: str = ""
    kill_criteria: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
