"""Unit tests for the portfolio orchestration module (workstream A).

Run either with pytest (``.venv/bin/python3 -m pytest``) or as a plain
assert runner (``.venv/bin/python3 src/trading/tests/test_portfolio.py``);
pytest is not currently installed in ``.venv``, so the ``__main__`` block is
the canonical invocation until it is.

Governing notes (design-derived tests, ledger rule M4):
- DEC-008  : contract conversion ``contracts = round(z / cap * L_max)``,
  ``L_max = floor(capital * safety_factor / (margin_rate * price * 100_000))``
- DEC-006  : milestone-1 scalar cost model (``HarnessParams.cost_per_side``)
- OBS-009 / OBS-010 : entrade margin rate 5% and 100,000 VND multiplier
- canon STG-1-CANONICAL-SIM / STG-5-POSITION-CONSTRUCTION : score->position
  and vol-targeting contracts implemented here

Test-mapping ledger notes (TST-*) are owned by the integrator; none are
written from this workstream.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import alpha_core

from trading.contracts import PortfolioConfig
from trading.portfolio import (
    SEED_EXPRESSIONS,
    WARMUP_MARGIN,
    PortfolioOrchestrator,
    default_seed_portfolio_config,
)

TS = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _synthetic(n: int, kind: str = "moderate") -> dict[str, list[float]]:
    """Deterministic synthetic bars (no RNG).

    ``kind="moderate"``: net uptrend with deterministic oscillation, so
    returns vary and the trailing z-score/vol estimates are meaningful.
    ``kind="const"``: constant close/volume.
    """
    close: list[float] = []
    volume: list[float] = []
    for t in range(n):
        if kind == "const":
            close.append(1500.0)
            volume.append(1000.0)
        else:
            c = 1000.0 * math.exp(
                0.00025 * t + 0.01 * math.sin(t * 0.07) + 0.005 * math.sin(t * 0.013)
            )
            close.append(c)
            volume.append(1000.0 + 200.0 * math.sin(t * 0.1) + 0.2 * t)
    return {"close": close, "volume": volume}


def _raises(exc: type[BaseException], fn) -> None:
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__} to be raised")


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


# --- required behaviours -----------------------------------------------------

def test_deterministic_on_fixed_bars() -> None:
    """Same bars -> byte-identical target, same and across instances."""
    bars = _synthetic(2000)
    po = PortfolioOrchestrator(default_seed_portfolio_config())
    a = po.compute_target(bars, TS)
    b = po.compute_target(bars, TS)
    _assert(a == b, "two calls on identical bars must return equal targets")
    po2 = PortfolioOrchestrator(default_seed_portfolio_config())
    _assert(
        po2.compute_target(bars, TS) == a,
        "independent orchestrators must agree on identical bars",
    )


def test_flat_on_constant_bars() -> None:
    """Constant close/volume -> zero signal, reason flat-no-signal (STG-1:
    a degenerate score maps to a flat position)."""
    bars = _synthetic(2000, kind="const")
    t = PortfolioOrchestrator(default_seed_portfolio_config()).compute_target(bars, TS)
    _assert(t.target_contracts == 0, "constant bars must yield zero contracts")
    _assert(t.reason == "flat-no-signal", f"reason={t.reason!r}")
    _assert(t.z_target == 0.0, "z_target must be zero on constant bars")
    _assert(
        all(v == 0.0 for v in t.components.values()),
        "all per-alpha components must be flat on constant bars",
    )


def test_warmup_returns_flat() -> None:
    """Buffer shorter than z_window + WARMUP_MARGIN -> flat, reason warmup."""
    cfg = default_seed_portfolio_config()
    po = PortfolioOrchestrator(cfg)
    min_bars = cfg.harness.z_window + WARMUP_MARGIN
    t = po.compute_target(_synthetic(min_bars - 1), TS)
    _assert(t.target_contracts == 0 and t.reason == "warmup", "short buffer -> warmup")
    t = po.compute_target(_synthetic(100), TS)
    _assert(t.target_contracts == 0 and t.reason == "warmup", "tiny buffer -> warmup")
    # unequal lengths
    bars = {"close": _synthetic(900)["close"], "volume": _synthetic(800)["volume"]}
    t = po.compute_target(bars, TS)
    _assert(t.target_contracts == 0 and t.reason == "warmup", "unequal lengths -> warmup")
    # empty
    t = po.compute_target({"close": [], "volume": []}, TS)
    _assert(t.target_contracts == 0 and t.reason == "warmup", "empty buffer -> warmup")


def test_contracts_bounded_by_max_contracts() -> None:
    """DEC-008 conversion output never exceeds max_contracts in magnitude."""
    cfg = default_seed_portfolio_config()
    po = PortfolioOrchestrator(cfg)
    for n in range(800, 2001, 100):
        t = po.compute_target(_synthetic(n), TS)
        _assert(
            abs(t.target_contracts) <= cfg.max_contracts,
            f"n={n}: |contracts|={abs(t.target_contracts)} exceeds max_contracts",
        )


def test_seed_expressions_all_validate() -> None:
    """All 6 seed DSL expressions round-trip through the engine validator."""
    _assert(len(SEED_EXPRESSIONS) == 6, "seed set must hold 6 expressions")
    for expr in SEED_EXPRESSIONS:
        canonical = alpha_core.validate_expression_py(expr)
        _assert(isinstance(canonical, str) and canonical, f"bad canonical form for {expr!r}")


def test_trending_series_nonflat_across_sweep() -> None:
    """A trending series must produce a non-flat target at least once across
    a sweep of buffer lengths (STG-1/STG-5: real signal -> non-zero z)."""
    po = PortfolioOrchestrator(default_seed_portfolio_config())
    non_flat = [
        po.compute_target(_synthetic(n), TS).target_contracts
        for n in range(800, 2001, 100)
    ]
    _assert(
        any(c != 0 for c in non_flat),
        f"expected at least one non-flat target, got {non_flat}",
    )


def test_invalid_inputs_flat() -> None:
    """Non-finite or non-positive price data -> flat, reason invalid-input."""
    po = PortfolioOrchestrator(default_seed_portfolio_config())
    bars = _synthetic(2000)
    bars["close"][5] = math.nan
    _assert(po.compute_target(bars, TS).reason == "invalid-input", "NaN close")
    bars = _synthetic(2000)
    bars["volume"][10] = math.inf
    _assert(po.compute_target(bars, TS).reason == "invalid-input", "inf volume")
    bars = _synthetic(2000)
    bars["close"][-1] = -5.0
    _assert(po.compute_target(bars, TS).reason == "invalid-input", "negative price")
    bars = _synthetic(2000)
    bars["close"][0] = 0.0
    _assert(po.compute_target(bars, TS).reason == "invalid-input", "zero price")
    _assert(po.compute_target({"close": _synthetic(900)["close"]}, TS).reason == "invalid-input",
            "missing volume key")


def test_init_rejects_bad_config() -> None:
    """Construction fails fast on invalid expressions/weights/harness."""
    good = default_seed_portfolio_config()
    bad_expr = PortfolioConfig(expressions=("not valid !!",), weights=(1.0,))
    _raises(ValueError, lambda: PortfolioOrchestrator(bad_expr))
    bad_w = PortfolioConfig(expressions=good.expressions, weights=(1.0,))
    _raises(ValueError, lambda: PortfolioOrchestrator(bad_w))
    bad_cap = PortfolioConfig(
        expressions=good.expressions,
        weights=good.weights,
        harness=type(good.harness)(cap=0.0),
    )
    _raises(ValueError, lambda: PortfolioOrchestrator(bad_cap))


def _run_all() -> None:
    tests = [
        fn
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"OK: {len(tests)} tests passed")


if __name__ == "__main__":
    _run_all()
