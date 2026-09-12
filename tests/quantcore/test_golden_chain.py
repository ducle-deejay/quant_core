# spec: 40-tests.md A — golden tests vs PRE-redesign system (full catalog)

import numpy as np
import pandas as pd
import pytest

from core.artifacts import AlphaPool, PoolEntry
from quantcore.alpha import AlphaConfig, evaluate_seed
from quantcore.execution import backtest_execution
from quantcore.portfolio import combine, refit_weights, score_pool
from quantcore.risk import backtest_portfolio
from trading.portfolio import SEED_EXPRESSIONS

pytestmark = pytest.mark.integration


def close(a, b, tol=1e-12):
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


@pytest.fixture(scope="module")
def chain(full_bars):
    """The full research chain on the real catalog (spec-sanctioned recipe)."""
    pool = AlphaPool(instrument=full_bars.instrument_id)
    sheets = {}
    acfg = AlphaConfig()
    for i, dsl in enumerate(SEED_EXPRESSIONS):
        sheet = evaluate_seed(dsl, full_bars, acfg)
        sheets[dsl] = sheet
        pool.add(PoolEntry(alpha_id=f"golden_seed_{i}", dsl=dsl, tear_sheet=sheet))
    scores = score_pool(pool, full_bars)
    composite = combine(scores, window=full_bars.window)
    result = backtest_portfolio(composite, full_bars)
    return {"pool": pool, "sheets": sheets, "composite": composite, "result": result}


def test_golden_alpha_metrics(chain, goldens):
    for dsl, sheet in chain["sheets"].items():
        for key, expected in goldens["alpha_metrics"][dsl].items():
            actual = sheet.metrics.get(key)
            assert actual is not None, f"missing metric {key} for {dsl}"
            if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                assert close(actual, expected), f"{dsl}.{key}: {actual} vs {expected}"
            else:
                assert actual == expected, f"{dsl}.{key}: {actual!r} vs {expected!r}"


def test_golden_combine_weights(chain, goldens):
    composite = chain["composite"]
    id_to_dsl = {e.alpha_id: e.dsl for e in chain["pool"].entries}
    for dsl, expected in goldens["combine_weights"].items():
        actual = next(
            w
            for aid, w in zip(composite.alpha_ids, composite.weights)
            if id_to_dsl[aid] == dsl
        )
        assert close(actual, expected), f"{dsl}: {actual} vs {expected}"


def test_golden_risk_performance(chain, goldens):
    result = chain["result"]
    for side in ("before", "after"):
        report = getattr(result, side)
        for key, expected in goldens["risk_before_after"][side]["performance"].items():
            assert close(report.performance[key], expected), f"{side}.{key}"
        for key, expected in goldens["risk_before_after"][side]["risk_process"].items():
            actual = report.risk_process[key]
            if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                assert close(actual, expected), f"{side}.{key}: {actual} vs {expected}"
            else:
                assert actual == expected, f"{side}.{key}"


def test_golden_target_series(chain, goldens):
    ts_g = goldens["risk_target_series"]
    series = chain["result"].targets.target_contracts
    assert [int(x) for x in series[:20]] == ts_g["after_head20"]
    assert close(sum(abs(int(x)) for x in series), ts_g["after_sum_abs"])
    n_changes = int(sum(1 for a, b in zip(series[1:], series[:-1]) if a != b))
    assert n_changes == ts_g["after_n_changes"]
    assert len(series) == ts_g["n"]


def test_golden_execution_handoff_works(chain, full_bars):
    """Old chain produced 0 orders (known break); the new handoff must trade."""
    targets = chain["result"].targets
    tc = targets.target_contracts
    change_idx = [i for i in range(1, len(tc)) if tc[i] != tc[i - 1]]
    assert change_idx, "golden targets never change — test window invalid"
    i0 = max(0, change_idx[0] - 2000)
    i1 = min(len(tc), change_idx[-1] + 2000)
    from core.data import BarFrame

    bars = BarFrame(
        ts=full_bars.ts[i0:i1],
        open=full_bars.open[i0:i1],
        high=full_bars.high[i0:i1],
        low=full_bars.low[i0:i1],
        close=full_bars.close[i0:i1],
        volume=full_bars.volume[i0:i1],
        instrument_id=full_bars.instrument_id,
        bar_type=full_bars.bar_type,
    )
    from core.artifacts import TargetSeries

    exec_targets = TargetSeries(
        ts=bars.ts,
        target_contracts=tc[i0:i1],
        window=bars.window,
        instrument=targets.instrument,
    )
    report = backtest_execution(exec_targets, bars)
    assert report.n_orders > 0
    assert report.n_fills > 0
    assert np.isfinite(report.slippage_bps_mean)


def test_refit_weights_sum_to_one(chain, full_bars):
    artifact = refit_weights(chain["pool"], full_bars)
    assert close(sum(artifact.weights.values()), 1.0, 1e-9)
