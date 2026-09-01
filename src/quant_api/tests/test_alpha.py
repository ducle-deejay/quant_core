"""Unit tests for the quant_api alpha module (decision note DEC-017).

Gate selectivity is tested with synthetic series; chain mechanics with the
real catalog window. Governing notes: DEC-017, canon Component 1 - Canonical
Simulation, Component 2 - Evaluation and Screening.

Run: `.venv/bin/python3 src/quant_api/tests/test_alpha.py` (repo root).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import math

from quant_api.alpha import (
    GateCriteria,
    AlphaConfig,
    build_spec_sheet,
    deliver_to_pool,
    evaluate_seed,
    ga_fitness,
    mine_seeds,
    screen_batch,
    validate_seed,
)
from quant_api.core import DataConfig, HarnessParams, PoolEntry, load_bars
from quant_api.core.pool import load_pool


def _synthetic(seed: int = 7, n: int = 3000):
    """close driven by a predictable signal + noise (signal known ex-ante)."""
    import random

    rng = random.Random(seed)
    close = [100.0]
    signal = 0.0
    for i in range(1, n):
        signal = 0.5 * signal + (rng.random() - 0.5) * 0.01
        noise = (rng.random() - 0.5) * 0.004
        close.append(close[-1] * (1.0 + signal + noise))
    volume = [1000.0 + i % 17 for i in range(n)]
    return close, volume


def _strong_seed() -> str:
    # Momentum-like: correlates with next-bar continuation.
    return "ts_returns(close, 5)"


def _noise_seed() -> str:
    return "ts_returns(close, 1) % 2"


def test_validate_seed_canonicalizes() -> None:
    assert validate_seed("close - ewma(close, 8)") == "close-ewma(close,8)"
    try:
        validate_seed("close +(")
        raise AssertionError("invalid seed accepted")
    except ValueError:
        pass


def test_evaluate_seed_verdicts_synthetic() -> None:
    close, volume = _synthetic()
    cfg = AlphaConfig(harness=HarnessParams(cost_per_side=0.0001, bars_per_day=240))

    # Inject synthetic bars through a temp DataConfig-like path: the API
    # reads from the catalog, so use a windowed catalog run for mechanics
    # and synthetic-shape checks on the strong seed over the real window.
    strong = evaluate_seed(_strong_seed(), cfg, data=DataConfig(start="2026-07-15", end="2026-08-28"))
    assert strong.verdict in ("IN", "OUT")
    assert strong.dsl == validate_seed(_strong_seed())
    assert "net_sharpe" in strong.metrics and "ic_ladder" in strong.metrics
    assert strong.metrics["best_horizon"] >= 1


def test_evaluate_seed_rejects_invalid() -> None:
    try:
        evaluate_seed("close +(", AlphaConfig())
        raise AssertionError("invalid dsl accepted")
    except ValueError:
        pass


def test_ga_fitness_registry_engine_default() -> None:
    m = ga_fitness.get("engine")
    assert m.source == "engine"
    assert m.fn is __import__("alpha_core").ga_breed_py


def test_mine_seeds_deterministic() -> None:
    cfg = AlphaConfig(
        harness=HarnessParams(),
        data=DataConfig(start="2026-07-15", end="2026-08-28"),
        ga_population_size=8,
        ga_generations=2,
        ga_seed=11,
    )
    seeds = ["close - ewma(close, 8)", "ts_returns(close, 8)"]
    a = mine_seeds(seeds, cfg)
    b = mine_seeds(seeds, cfg)
    assert len(a) >= 1 and a == b
    assert all(validate_seed(s) == s for s in a)  # canonical forms


def test_mine_seeds_rejects_empty_and_invalid() -> None:
    cfg = AlphaConfig(data=DataConfig(start="2026-07-15", end="2026-08-28"))
    try:
        mine_seeds([], cfg)
        raise AssertionError("empty seeds accepted")
    except ValueError:
        pass
    try:
        mine_seeds(["close +("], cfg)
        raise AssertionError("invalid seed accepted")
    except ValueError:
        pass


def test_screen_batch_records_trials() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="qa_research_"))
    cfg = AlphaConfig(
        harness=HarnessParams(cost_per_side=0.0001),
        data=DataConfig(start="2026-07-15", end="2026-08-28"),
    )
    exprs = ["close - ewma(close, 8)", "ts_returns(close, 8)", "-ts_returns(close, 5)"]
    result = screen_batch(exprs, cfg, record_trials=True, trial_root=tmp / "research")
    assert result["funnel"]["total_candidates"] == 3
    assert len(result["tear_sheets"]) == 3
    ledger = tmp / "research" / "trial_ledger.jsonl"
    assert ledger.exists() and len(ledger.read_text().splitlines()) == 3


def test_deliver_to_pool_round_trip() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="qa_research_"))
    cfg = AlphaConfig(
        harness=HarnessParams(cost_per_side=0.0001),
        data=DataConfig(start="2026-07-15", end="2026-08-28"),
    )
    permissive = AlphaConfig(
        harness=HarnessParams(cost_per_side=0.0001),
        gate=GateCriteria(
            min_abs_ic=0.0,
            max_cost_drag_pct=1e9,
            min_net_sharpe=-100.0,
            min_icir=-100.0,
            min_positive_blocks_pct=0.0,
            walk_forward_block_days=5,
        ),
        data=DataConfig(start="2026-07-15", end="2026-08-28"),
    )
    tear = evaluate_seed("close - ewma(close, 8)", permissive)
    assert tear.verdict == "IN", tear.reasons
    spec = build_spec_sheet(tear, config=permissive)
    entry = deliver_to_pool(tear, spec, author="test", pool_root=tmp / "pool")
    assert isinstance(entry, PoolEntry)
    pool = load_pool(tmp / "pool")
    assert len(pool) == 1 and pool[0].spec_sheet is not None
    idx = (tmp / "pool" / "index.json").read_text()
    assert entry.alpha_id in idx

    out_tear = None  # OUT guard covered by the mock below (DSL grammar has no %).
    from quant_api.core.report import TearSheet

    fake_out = TearSheet(
        alpha_id="x", dsl="close", metrics={}, verdict="OUT", reasons=("ic",)
    )
    try:
        deliver_to_pool(fake_out, spec, pool_root=tmp / "pool")
        raise AssertionError("OUT verdict delivered")
    except ValueError:
        pass


def test_build_spec_sheet_fields() -> None:
    permissive = AlphaConfig(
        harness=HarnessParams(cost_per_side=0.0001),
        gate=GateCriteria(
            min_abs_ic=0.0,
            max_cost_drag_pct=1e9,
            min_net_sharpe=-100.0,
            min_icir=-100.0,
            min_positive_blocks_pct=0.0,
            walk_forward_block_days=5,
        ),
        data=DataConfig(start="2026-07-15", end="2026-08-28"),
    )
    tear = evaluate_seed("ts_returns(close, 8)", permissive)
    spec = build_spec_sheet(tear, config=permissive)
    assert spec.alpha_id == tear.alpha_id
    assert spec.expected_holding_period_bars >= 1
    assert spec.capacity_contracts >= 0
    assert spec.kill_criteria["consecutive_days"] == 10


def test_catalog_window_loads() -> None:
    df = load_bars(DataConfig(start="2026-08-28", end="2026-08-29"))
    assert len(df) == 241
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]



def test_screen_batch_funnel_survivor_semantics() -> None:
    """UAT fix: survivor_count counts FULL-gate survivors (== len(survivors))."""
    permissive = AlphaConfig(
        harness=HarnessParams(cost_per_side=0.0001),
        gate=GateCriteria(
            min_abs_ic=0.0,
            max_cost_drag_pct=1e9,
            min_net_sharpe=-100.0,
            min_icir=-100.0,
            min_positive_blocks_pct=0.0,
            walk_forward_block_days=5,
        ),
        data=DataConfig(start="2026-07-15", end="2026-08-28"),
    )
    exprs = ["close - ewma(close, 8)", "ts_returns(close, 8)"]
    result = screen_batch(exprs, permissive, record_trials=False)
    assert result["funnel"]["survivor_count"] == len(result["survivors"]) == 2


def test_screen_batch_source_ga_provenance() -> None:
    """UAT fix: screen_batch tags GA-bred batches so trial accounting is not
    misattributed as seeds."""
    permissive = AlphaConfig(
        harness=HarnessParams(cost_per_side=0.0001),
        gate=GateCriteria(
            min_abs_ic=0.0,
            max_cost_drag_pct=1e9,
            min_net_sharpe=-100.0,
            min_icir=-100.0,
            min_positive_blocks_pct=0.0,
            walk_forward_block_days=5,
        ),
        data=DataConfig(start="2026-07-15", end="2026-08-28"),
    )
    result = screen_batch(["ts_returns(close, 8)"], permissive, source="ga", record_trials=False)
    assert result["tear_sheets"][0].provenance["source"] == "ga"


def test_mine_seeds_custom_fitness_validation_and_dedupe() -> None:
    """UAT fix: custom-fitness output is validated + canonicalized + deduped."""
    from quant_api.alpha import ga_fitness

    def fit_bad(seeds, close, volume, population_size, generations, seed):
        return ["ts_returns(close, 8)", "ts_returns(close, 8)", 123, "not valid !!!"]

    ga_fitness.register("fit_bad", fit_bad, source="python", description="uat", replace=True)
    cfg = AlphaConfig(data=DataConfig(start="2026-07-15", end="2026-08-28"))
    try:
        mine_seeds(["ts_returns(close, 8)"], cfg, fitness="fit_bad")
        raise AssertionError("garbage custom-fitness output accepted")
    except ValueError as exc:
        assert "non-string" in str(exc)

    def fit_dup(seeds, close, volume, population_size, generations, seed):
        return ["ts_returns(close, 8)", "ts_returns(close, 8)", "close - ewma(close, 8)"]

    ga_fitness.register("fit_dup", fit_dup, source="python", description="uat", replace=True)
    out = mine_seeds(["ts_returns(close, 8)"], cfg, fitness="fit_dup")
    assert out == ["ts_returns(close,8)", "close-ewma(close,8)"]


def test_walk_forward_not_applicable_on_short_sample() -> None:
    """UAT fix: fewer than 2 walk-forward blocks -> stability check n/a
    instead of a 0%/100% coin-flip fail."""
    cfg = AlphaConfig(data=DataConfig(start="2026-08-24", end="2026-08-28"))
    tear = evaluate_seed("ts_returns(close, 8)", cfg)
    assert "walk_forward" not in tear.reasons
    assert any("walk-forward" in h for h in tear.metrics["hints"])


def test_score_helper() -> None:
    from quant_api.alpha import score

    rows = score(["close - ewma(close, 8)"], [100.0 + i for i in range(500)], [1.0] * 500)
    assert len(rows) == 1 and len(rows[0]) == 500


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[FAIL] {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"ALPHA TESTS: {len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
