"""Full-chain integration test for the quant_api role modules (DEC-017).

Chain: seed -> single-alpha evaluation -> GA mining -> pool delivery ->
pool scores -> combination -> portfolio backtest (sizing + risk policy).

The chain runs on a real catalog window (2026-07-15 .. 2026-08-28, the
paper-session warmup window) with a PERMISSIVE gate: this test verifies the
handoff mechanics between the four role modules, not gate selectivity
(gate selectivity is unit-tested with synthetic data in each module's
tests). Governing note: DEC-017; canon names in full where cited.

Run: `.venv/bin/python3 src/quant_api/tests/test_integration.py` (repo root).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import tempfile

from quant_api.core import DataConfig, HarnessParams, load_bars
from quant_api.core.pool import load_pool

WINDOW = DataConfig(start="2026-07-15", end="2026-08-28")
SEEDS = ("close - ewma(close, 8)", "ts_returns(close, 8)", "-ts_returns(close, 5)")


def _permissive_config():
    """Chain-mechanics config: every finite-metric candidate passes the gate."""
    from quant_api.research import GateCriteria, ResearchConfig

    gate = GateCriteria(
        min_abs_ic=0.0,
        max_cost_drag_pct=1e9,
        min_net_sharpe=-100.0,
        min_icir=-100.0,
        min_positive_blocks_pct=0.0,
        walk_forward_block_days=5,
    )
    return ResearchConfig(
        harness=HarnessParams(),
        gate=gate,
        data=WINDOW,
        ga_population_size=8,
        ga_generations=2,
        ga_seed=7,
    )


def test_full_chain() -> None:
    from quant_api.research import (
        build_spec_sheet,
        deliver_to_pool,
        evaluate_candidate,
        evaluate_seed,
        mine_seeds,
        screen_batch,
        validate_seed,
    )

    cfg = _permissive_config()

    # 1. Seed -> single-alpha evaluation (Component 1 + Component 2).
    bars = load_bars(WINDOW)
    assert len(bars) >= 7000, f"window too small for integration test: {len(bars)}"
    tear = evaluate_seed(SEEDS[0], cfg, record_trial=False)
    assert tear.verdict in ("IN", "OUT")
    assert tear.dsl == validate_seed(SEEDS[0]), "tear sheet carries the canonical DSL"
    assert "net_sharpe" in tear.metrics and "ic_ladder" in tear.metrics

    # 2. Screen a small batch (trial accounting in a temp ledger).
    funnel = screen_batch(list(SEEDS), cfg, record_trials=True, trial_root=tmp("research"))
    assert funnel["funnel"]["total_candidates"] == len(SEEDS)
    assert len(funnel["tear_sheets"]) == len(SEEDS)

    # 3. GA mining breeds from the seeds (engine binding, deterministic).
    bred = mine_seeds(list(SEEDS), cfg)
    assert len(bred) >= 1
    assert bred == mine_seeds(list(SEEDS), cfg), "GA breeding must be seed-deterministic"

    # 4. Candidate evaluation + pool delivery (handoff artifact).
    cand = evaluate_candidate(bred[0], cfg, record_trial=False)
    assert cand.verdict == "IN", f"permissive gate must admit the bred candidate: {cand.reasons}"
    spec = build_spec_sheet(cand, config=cfg)
    assert spec.expected_holding_period_bars >= 1 and spec.capacity_contracts >= 0
    entry = deliver_to_pool(cand, spec, author="integration", tags=("e2e",), pool_root=tmp("pool"))
    assert entry.alpha_id and entry.dsl == bred[0]
    pool = load_pool(tmp("pool"))
    assert len(pool) == 1 and pool[0].alpha_id == entry.alpha_id

    # 5. Portfolio: pool scores -> combine -> refit weights.
    from quant_api.portfolio import combine, pool_scores, refit_weights

    scores = pool_scores(pool, data=WINDOW)
    assert set(scores) == {entry.alpha_id}
    combined = combine(scores, method="inverse_vol")
    assert len(combined["composite"]) == len(bars)
    assert combined["provenance"]["source"] == "engine"
    refit = refit_weights(pool, data=WINDOW, method="inverse_vol", save=False)
    w = refit["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-6, f"weights must sum to 1: {w}"

    # 6. Risk: portfolio backtest with sizing + trigger-matrix policy.
    from quant_api.risk import RiskBacktestConfig, backtest_portfolio

    risk_cfg = RiskBacktestConfig(data=WINDOW)
    report = backtest_portfolio(combined["composite"], data=WINDOW, config=risk_cfg)
    for side in ("before", "after"):
        assert "performance" in report[side] and "risk_process" in report[side]
        assert "net_sharpe" in report[side]["performance"]
        assert "n_interventions" in report[side]["risk_process"]
    assert isinstance(report["interventions"], list)


def tmp(sub: str) -> str:
    """One shared temp root per test run (created lazily)."""
    global _TMP_ROOT
    if _TMP_ROOT is None:
        _TMP_ROOT = Path(tempfile.mkdtemp(prefix="quant_api_integration_"))
    root = _TMP_ROOT / sub
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


_TMP_ROOT: Path | None = None


if __name__ == "__main__":
    test_full_chain()
    print("INTEGRATION: PASS")
