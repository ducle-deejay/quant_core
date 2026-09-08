"""Handoff artifact writers (DEC-017).

Only artifacts consumed by another role or by the live system are
auto-saved: trial ledger, pool (see ``quantcore.core.pool``), weights,
weekly slippage summary, risk overlay config. Researcher-facing reports
(tear sheets, backtest reports, gauge reports, post-mortems) are NOT
written here - they stay in-memory and are exported on demand.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from quantcore.core.config import REPO_ROOT

#: Default artifact roots (all under <repo>/data).
DEFAULT_RESEARCH_DIR = REPO_ROOT / "data" / "research"
DEFAULT_POOL_DIR = REPO_ROOT / "data" / "pool"
DEFAULT_STATE_DIR = REPO_ROOT / "data" / "state"


def _ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict) -> Path:
    _ensure_parent(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )
    return path


def append_trial_ledger(entry: dict, root: Path | None = None) -> Path:
    """Append one trial record as a JSONL line (append-only, canon Component 2).

    Consumers: deflated-threshold trial count, mining family priors,
    post-mortem. Entry should carry at least: alpha_id, dsl, date, verdict,
    metrics summary, provenance.
    """
    path = _ensure_parent(Path(root or DEFAULT_RESEARCH_DIR) / "trial_ledger.jsonl")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def write_weights(weights: dict, root: Path | None = None) -> Path:
    """Persist refit weights; consumed by the live ``PortfolioConfig``.

    Payload shape: {"generated": ..., "method": ..., "weights": {alpha_id: w},
    "provenance": {...}}.
    """
    return _write_json(Path(root or DEFAULT_POOL_DIR) / "weights.json", weights)


def write_slippage_summary(
    summary: dict, week: str | None = None, root: Path | None = None
) -> Path:
    """Persist the weekly slippage summary; consumed by cost-model
    recalibration (feedback 7->1) and sizing buffers."""
    week = week or date.today().isoformat()
    return _write_json(
        Path(root or DEFAULT_RESEARCH_DIR) / f"slippage_{week}.json", summary
    )


def write_risk_overlay_config(config: dict, root: Path | None = None) -> Path:
    """Persist the validated live risk overlay config; consumed by the live
    overlay wiring (``trading.risk.state.RiskConfig``)."""
    return _write_json(Path(root or DEFAULT_STATE_DIR) / "risk_overlay.json", config)
