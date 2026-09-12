"""Golden parity tests — new API vs recorded pre-redesign outputs.

apply_policy=True must reproduce the old "after" side exactly; the default
(apply_policy=False) headline must reproduce the old "before" side.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytestmark = pytest.mark.integration


def close(a, b, tol=1e-12):
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


@pytest.fixture(scope="module")
def chain(full_bars):
    import pandas as pd  # noqa: F401

    from core.artifacts import AlphaPool, PoolEntry
    from quantcore.alpha import AlphaConfig, evaluate_seed
    from quantcore.portfolio import combine, score_pool
    from quantcore.risk import backtest_portfolio
    from strategy.portfolio import SEED_EXPRESSIONS

    pool = AlphaPool(instrument=full_bars.instrument_id)
    sheets = {}
    acfg = AlphaConfig()
    for i, dsl in enumerate(SEED_EXPRESSIONS):
        sheet = evaluate_seed(dsl, full_bars, acfg)
        sheets[dsl] = sheet
        pool.add(PoolEntry(alpha_id=f"golden_seed_{i}", dsl=dsl, tear_sheet=sheet))
    scores = score_pool(pool, full_bars)
    composite = combine(scores, window=full_bars.window)
    applied = backtest_portfolio(composite, full_bars, apply_policy=True)
    headline = backtest_portfolio(composite, full_bars)
    return {"applied": applied, "headline": headline}


def test_headline_is_raw_strategy_performance(chain, goldens):
    expected = goldens["risk_before_after"]["before"]["performance"]
    perf = chain["headline"].performance
    assert close(perf["net_sharpe"], expected["net_sharpe"])
    assert close(perf["max_drawdown"], expected["max_drawdown"])
    assert close(perf["total_net_pnl"], expected["total_net_pnl"])


def test_headline_targets_are_before_series(chain, goldens):
    ts_g = goldens["risk_target_series"]
    series = chain["headline"].targets.target_contracts
    assert [int(x) for x in series[:20]] == ts_g["before_head20"]
    assert close(sum(abs(int(x)) for x in series), ts_g["before_sum_abs"])


def test_applied_policy_performance_parity(chain, goldens):
    for side in ("before", "after"):
        expected_perf = goldens["risk_before_after"][side]["performance"]
        source = (
            chain["applied"].before_performance
            if side == "before"
            else chain["applied"].performance
        )
        for key, exp in expected_perf.items():
            assert close(source[key], exp), f"{side}.{key}"


def test_applied_policy_risk_process_parity(chain, goldens):
    after_proc = chain["applied"].policy
    expected = goldens["risk_before_after"]["after"]["risk_process"]
    for key, exp in expected.items():
        actual = after_proc.get(key)
        if isinstance(exp, (int, float)) and isinstance(actual, (int, float)):
            assert close(actual, exp), f"{key}: {actual} vs {exp}"
        else:
            assert actual == exp, f"{key}"


def test_applied_policy_targets_parity(chain, goldens):
    ts_g = goldens["risk_target_series"]
    series = chain["applied"].targets.target_contracts
    assert [int(x) for x in series[:20]] == ts_g["after_head20"]
    assert close(sum(abs(int(x)) for x in series), ts_g["after_sum_abs"])
    n_changes = int(
        sum(1 for a, b in zip(series[1:], series[:-1]) if a != b)
    )
    assert n_changes == ts_g["after_n_changes"]
    assert len(series) == ts_g["n"]


def test_default_headline_has_no_policy_payload(chain):
    assert chain["headline"].policy is None
    assert chain["headline"].interventions == []
    assert chain["headline"].before_performance is not None
