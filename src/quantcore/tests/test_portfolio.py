"""Contract tests for quantcore.portfolio (Portfolio Researcher API).

Governing notes (ledger rule M4): decision note DEC-017 (quantcore role
modules - portfolio role scope, registry/provenance, artifact discipline) and
the canon stage names Component 3 - Orthogonalization / Component 4 -
Combination, with the capped-simplex algorithm documented in
src/alpha-core/src/strategies/combination/inverse_vol.rs.

Tests are deterministic, offline and fast: engine paths use synthetic lists
or a small catalog window (DataConfig(start="2026-08-28", end="2026-08-29")
= 241 bars); every file write goes under tempfile.mkdtemp().
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import alpha_core  # noqa: E402
import numpy as np  # noqa: E402

from quantcore.core.config import DataConfig, HarnessParams  # noqa: E402
from quantcore.core.pool import PoolEntry, load_pool, write_pool_entry, write_pool_index  # noqa: E402
from quantcore import portfolio as p  # noqa: E402

#: Small catalog window: 241 bars (one trading day, 2026-08-28).
SMALL = DataConfig(start="2026-08-28", end="2026-08-29")

#: Deterministic synthetic series for engine-path tests.
def _alternator(amp: float, n: int = 64) -> list[float]:
    return [amp if t % 2 == 0 else -amp for t in range(n)]


def _pool_two(tmp: str) -> list[PoolEntry]:
    """Write a 2-entry pool folder under ``tmp`` and return the entries."""
    entries = [
        PoolEntry(alpha_id="a_001", dsl="close - ewma(close, 8)"),
        PoolEntry(alpha_id="a_002", dsl="ts_returns(close, 8)"),
    ]
    for e in entries:
        write_pool_entry(e, root=tmp)
    write_pool_index(entries, root=tmp)
    return entries


# ---------------------------------------------------------------------------
# Registry and defaults
# ---------------------------------------------------------------------------

def test_combine_methods_registry_defaults() -> None:
    # DEC-017: one registry per slot; the two combine defaults are
    # engine-backed (source="engine") and registered at import.
    assert p.combine_methods.slot == "combine_methods"
    assert p.combine_methods.names() == ["equal_weight", "inverse_vol"]
    for name in ("equal_weight", "inverse_vol"):
        m = p.combine_methods.get(name)
        assert m.source == "engine", name
        assert callable(m.fn), name
    # Duplicate registration without replace is rejected (Registry contract).
    try:
        p.combine_methods.register("equal_weight", lambda s: s)
        raise AssertionError("duplicate registration must raise")
    except ValueError:
        pass


def test_equal_weight_defaults_and_explicit() -> None:
    # Component 4 - Combination: equal 1/N weights; explicit weights honored;
    # the weighted sum runs in the engine (research/live parity).
    scores = [[1.0, 2.0, 3.0], [3.0, 2.0, 1.0]]
    r = p.combine(scores, method="equal_weight")
    assert r["weights"] == {0: 0.5, 1: 0.5}
    assert r["provenance"] == {"method": "equal_weight", "source": "engine"}
    # Canon REC-009: weights are applied to STANDARDIZED rows.
    std = p._standardize(scores)
    expected = [0.5 * a + 0.5 * b for a, b in zip(*std)]
    assert all(abs(a - b) < 1e-12 for a, b in zip(r["composite"], expected))

    r2 = p.combine(scores, method="equal_weight", weights=[0.25, 0.75])
    expected2 = [0.25 * a + 0.75 * b for a, b in zip(*std)]
    assert r2["weights"] == {0: 0.25, 1: 0.75}
    assert all(abs(a - b) < 1e-12 for a, b in zip(r2["composite"], expected2))

    # Wrong arity must raise before touching the engine.
    try:
        p.combine(scores, method="equal_weight", weights=[0.5])
        raise AssertionError("wrong weight count must raise")
    except ValueError:
        pass


def test_combine_dict_input_keys_sorted() -> None:
    # dict input: weights keyed by alpha_id, series ordered by sorted id.
    scores = {"z_alpha": [1.0, -1.0], "a_alpha": [2.0, 2.0]}
    r = p.combine(scores, method="equal_weight")
    assert list(r["weights"]) == ["a_alpha", "z_alpha"]
    assert r["weights"] == {"a_alpha": 0.5, "z_alpha": 0.5}
    # a_alpha is constant -> standardized row is zeros; z_alpha -> [-1, 1].
    assert r["composite"] == [0.5, -0.5]


def test_combine_rejects_bad_input() -> None:
    try:
        p.combine({})
        raise AssertionError("empty scores must raise")
    except ValueError:
        pass
    try:
        p.combine([[1.0], [1.0, 2.0]])
        raise AssertionError("unequal lengths must raise")
    except ValueError:
        pass
    try:
        p.combine([[1.0, 2.0]], method="nope")
        raise AssertionError("unknown method must raise")
    except KeyError:
        pass
    try:
        p.combine([[1.0, 2.0]], method="inverse_vol", weights=[1.0])
        raise AssertionError("weights with inverse_vol must raise")
    except ValueError:
        pass


def test_custom_python_method_provenance() -> None:
    # DEC-017: practitioners register research methods as plain Python
    # functions; provenance records source="python" (validate-then-migrate).
    def halve(scores):  # degenerate but deterministic research method
        return [s / 2.0 for s in scores[0]]

    p.combine_methods.register("test_halve", halve, source="python", description="test")
    try:
        r = p.combine([[1.0, 2.0], [3.0, 4.0]], method="test_halve")
        assert r["composite"] == [0.5, 1.0]
        assert r["provenance"] == {"method": "test_halve", "source": "python"}
        assert r["weights"] is None
    finally:
        # replace=True so re-runs stay idempotent.
        p.combine_methods.register(
            "test_halve", halve, source="python", description="test", replace=True
        )


# ---------------------------------------------------------------------------
# Inverse-vol weights mirror (Component 4 - Combination, inverse_vol.rs)
# ---------------------------------------------------------------------------

def test_inverse_vol_composite_matches_manual_weights() -> None:
    # Research-side weights must reproduce the engine composite exactly
    # (the engine used the same weights internally).
    scores = [_alternator(1.0), _alternator(2.0), _alternator(0.5)]
    r = p.combine(scores, method="inverse_vol")
    w = [r["weights"][i] for i in range(3)]
    assert abs(sum(w) - 1.0) < 1e-9
    std = p._standardize(scores)
    manual = [sum(wi * s[t] for wi, s in zip(w, std)) for t in range(64)]
    assert all(abs(a - b) < 1e-9 for a, b in zip(r["composite"], manual))


def test_inverse_vol_weights_closed_forms() -> None:
    # Rust contract cases from inverse_vol.rs (cap binds, floor binds).
    w = p._inverse_vol_weights([_alternator(1.0), _alternator(2.0), _alternator(0.5)])
    assert all(abs(a - b) < 1e-9 for a, b in zip(w, [1.0 / 3.0, 1.0 / 6.0, 0.5]))
    assert abs(sum(w) - 1.0) < 1e-9

    w2 = p._inverse_vol_weights([_alternator(100.0), _alternator(1.0), _alternator(1.0)])
    assert abs(w2[0] - 0.01) < 1e-9  # floor binds on the wild alpha
    assert all(x <= 0.5 + 1e-9 for x in w2)
    assert abs(sum(w2) - 1.0) < 1e-9

    # Zero-vol alpha excluded; lone survivor takes the full budget.
    w3 = p._inverse_vol_weights([_alternator(1.0), [3.0] * 64])
    assert w3 == [1.0, 0.0]

    # All-zero-vol pool falls back to equal weights.
    w4 = p._inverse_vol_weights([[1.0] * 32, [-2.0] * 32, [7.0] * 32])
    assert all(abs(x - 1.0 / 3.0) < 1e-12 for x in w4)

    # Single-alpha portfolio gets the full weight; empty input -> empty.
    assert p._inverse_vol_weights([_alternator(2.0, 16)]) == [1.0]
    assert p._inverse_vol_weights([]) == []


# ---------------------------------------------------------------------------
# Sanitization helper (OBS-011 mirror)
# ---------------------------------------------------------------------------

def test_sanitize_scores() -> None:
    assert p._sanitize_scores([float("nan"), float("nan"), 3.0, 4.0]) == [3.0, 3.0, 3.0, 4.0]
    assert p._sanitize_scores([1.0, float("nan"), float("inf"), 2.0]) == [1.0, 1.0, 1.0, 2.0]
    assert p._sanitize_scores([float("nan"), float("nan")]) == [0.0, 0.0]
    assert p._sanitize_scores([1.5, -2.0, 0.0]) == [1.5, -2.0, 0.0]


# ---------------------------------------------------------------------------
# Component 3 - Orthogonalization
# ---------------------------------------------------------------------------

def test_orthogonalize_redundant_when_in_span() -> None:
    # Candidate = 2 * pool member: fully absorbed, residual ~ 0 -> sharpe 0.
    pool_col = _alternator(1.0, 64)
    r = p.orthogonalize([2.0 * x for x in pool_col], [pool_col])
    assert r["verdict"] == "REDUNDANT"
    assert r["residual_sharpe"] == 0.0
    assert r["note"]


def test_orthogonalize_incremental_with_residual_signal() -> None:
    # Candidate = pool + positive-trend residual: the orthogonalized part
    # keeps a positive mean, so its annualized Sharpe is positive. The
    # residual Sharpe is computed on DAILY aggregation, so the sample must
    # span >= 2 days (n >= 2 * bars_per_day).
    n = 960
    pool_col = [math.sin(t * 0.3) for t in range(n)]
    trend = [0.05 * t for t in range(n)]
    candidate = [a + b for a, b in zip(pool_col, trend)]
    r = p.orthogonalize(candidate, [pool_col])
    assert r["verdict"] == "INCREMENTAL"
    assert math.isfinite(r["residual_sharpe"]) and r["residual_sharpe"] > 0.0
    assert len(r["residual"]) == n and len(r["betas"]) == 1
    assert math.isfinite(r["r_squared"])


def test_orthogonalize_requires_finite_input() -> None:
    # Raw engine scores carry warmup NaN; callers must sanitize first
    # (OBS-011). The binding rejects non-finite input.
    try:
        p.orthogonalize([1.0, float("nan")], [[1.0, 1.0]])
        raise AssertionError("non-finite candidate must raise")
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# score_pool / pool I/O
# ---------------------------------------------------------------------------

def test_score_pool_small_window() -> None:
    # One engine batch call over the small catalog window; sanitized rows.
    with tempfile.TemporaryDirectory() as tmp:
        entries = _pool_two(tmp)
        scores = p.score_pool(entries, data=SMALL)
    assert set(scores) == {"a_001", "a_002"}
    for s in scores.values():
        assert len(s) == 241
        assert all(math.isfinite(v) for v in s)


def test_score_pool_empty_pool() -> None:
    assert p.score_pool([], data=SMALL) == {}


def test_score_pool_invalid_dsl_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = [PoolEntry(alpha_id="bad_1", dsl="close +")]
        write_pool_entry(bad[0], root=tmp)
        try:
            p.score_pool(bad, data=SMALL)
            raise AssertionError("invalid DSL must raise from the engine")
        except ValueError:
            pass


def test_load_pool_roundtrip() -> None:
    # Re-export of quantcore.core.pool.load_pool; folder is the source of
    # truth for the pool (DEC-017).
    with tempfile.TemporaryDirectory() as tmp:
        _pool_two(tmp)
        loaded = p.load_pool(root=tmp)
        assert [e.alpha_id for e in loaded] == ["a_001", "a_002"]
        assert loaded[0].dsl == "close - ewma(close, 8)"


# ---------------------------------------------------------------------------
# refit_weights (weekly cadence, Component 4 - Combination)
# ---------------------------------------------------------------------------

def test_refit_weights_inverse_vol_saves_artifact() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        entries = _pool_two(tmp)
        result = p.refit_weights(entries, data=SMALL, method="inverse_vol", root=tmp)
        assert set(result) == {"generated", "method", "weights", "provenance"}
        assert result["method"] == "inverse_vol"
        assert result["generated"] == date.today().isoformat()
        assert set(result["weights"]) == {"a_001", "a_002"}
        assert abs(sum(result["weights"].values()) - 1.0) < 1e-9
        assert result["provenance"] == {"method": "inverse_vol", "source": "engine"}
        # Handoff artifact consumed by the live PortfolioConfig (DEC-017).
        path = Path(tmp) / "weights.json"
        assert path.exists()
        saved = json.loads(path.read_text())
        assert saved == result


def test_refit_weights_equal_weight_no_save() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        entries = _pool_two(tmp)
        result = p.refit_weights(
            entries, data=SMALL, method="equal_weight", save=False, root=tmp
        )
        assert result["weights"] == {"a_001": 0.5, "a_002": 0.5}
        assert not (Path(tmp) / "weights.json").exists()


def test_refit_weights_window_days_filters() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        entries = _pool_two(tmp)
        result = p.refit_weights(entries, data=SMALL, window_days=1, save=False)
        assert set(result["weights"]) == {"a_001", "a_002"}
        # The 241-bar window is a single day, so a 1-day window keeps it all;
        # just assert determinism (same output twice).
        again = p.refit_weights(entries, data=SMALL, window_days=1, save=False)
        assert result["weights"] == again["weights"]


def test_refit_weights_guards() -> None:
    def throwaway(scores):  # registered research method, no derivation rule
        return scores[0]

    p.combine_methods.register(
        "test_guard_custom", throwaway, source="python", description="test", replace=True
    )
    with tempfile.TemporaryDirectory() as tmp:
        entries = _pool_two(tmp)
        try:
            p.refit_weights([], data=SMALL, save=False)
            raise AssertionError("empty pool must raise")
        except ValueError:
            pass
        try:
            p.refit_weights(entries, data=SMALL, method="test_guard_custom", save=False)
            raise AssertionError("custom method has no derivation rule; must raise")
        except ValueError:
            pass
        try:
            p.refit_weights(entries, data=SMALL, method="nope", save=False)
            raise AssertionError("unknown method must raise")
        except KeyError:
            pass


# ---------------------------------------------------------------------------
# portfolio_health_report (monthly review, Component 4 - Combination)
# ---------------------------------------------------------------------------

def test_portfolio_health_report_structure() -> None:
    # The monthly allocation-review input: in-memory, never auto-saved.
    with tempfile.TemporaryDirectory() as tmp:
        entries = _pool_two(tmp)
        rep = p.portfolio_health_report(entries, data=SMALL, window_days=30)
    assert rep["pool_size"] == 2
    assert rep["bars"] == 241
    assert rep["window_days"] == 30
    for key in (
        "full_sample_sharpe",
        "max_drawdown",
        "last_window_sharpe",
        "window_return",
        "rolling_mean_ic",
    ):
        assert math.isfinite(rep[key]), key
    assert -1.0 <= rep["rolling_mean_ic"] <= 1.0
    # The 241-bar window is shorter than z_window=480, so the canonical
    # position is flat and the PnL metrics are exactly zero (engine contract:
    # rolling_zscore returns zeros when n < window).
    assert rep["full_sample_sharpe"] == 0.0
    assert rep["max_drawdown"] == 0.0
    assert rep["last_window_sharpe"] == 0.0
    assert rep["window_return"] == 0.0
    # Verdict rule: refit when window sharpe < 0 or mean IC < 0.05.
    expected = "refit" if (rep["last_window_sharpe"] < 0.0 or rep["rolling_mean_ic"] < 0.05) else "ok"
    assert rep["verdict"] == expected
    assert rep["verdict"] in ("ok", "refit")


def test_portfolio_health_report_empty_pool_raises() -> None:
    try:
        p.portfolio_health_report([], data=SMALL)
        raise AssertionError("empty pool must raise")
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Harness wiring sanity
# ---------------------------------------------------------------------------

def test_harness_defaults_match_contracts() -> None:
    h = HarnessParams()
    assert (h.span, h.z_window, h.band, h.cap, h.bars_per_day) == (8, 480, 0.35, 2.0, 240)
    assert h.cost_per_side == 0.000229


def _run_all() -> None:
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001 - plain assert-runner
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    if failed:
        raise SystemExit(1)


def test_pool_pnl_helper() -> None:
    """UAT fix (REC-008): pool_pnl builds the canonical per-bar net PnL input
    for orthogonalize."""
    with tempfile.TemporaryDirectory() as tmp:
        entries = _pool_two(tmp)
        pnl = p.pool_pnl(entries, data=SMALL)
    assert set(pnl) == {"a_001", "a_002"}
    assert all(len(v) == 241 for v in pnl.values())
    assert all(all(math.isfinite(x) for x in v) for v in pnl.values())


if __name__ == "__main__":
    _run_all()
