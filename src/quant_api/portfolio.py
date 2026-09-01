"""quant_api.portfolio - Portfolio Researcher API (decision note DEC-017).

Role: Portfolio Researcher. Consumes the research pool (per-alpha files with
canonical DSL + metadata), orthogonalizes new candidates against it, combines
scores into a composite, refits the allocation weights on a cadence and
produces the monthly portfolio health report. Position sizing is owned by the
risk role (DEC-017) and is NOT in scope here.

Canon stage map (frozen design, docs/enhanced/):
- Component 3 - Orthogonalization : ``orthogonalize`` verdict
- Component 4 - Combination       : ``combine`` / ``refit_weights`` /
                                    ``portfolio_health_report``
- Component 1 - Canonical Simulation : canonical_map_py + compute_pnl_py are
                                    reused inside ``portfolio_health_report``

Extension (DEC-017): one registry per slot. ``combine_methods`` carries the
two engine-backed defaults (equal_weight, inverse_vol) registered at import
with ``source="engine"``; practitioners register research methods as plain
Python functions (``source="python"``) and migrate validated ones into the
Rust ``CombineMethod`` trait later (validate-then-migrate).

Artifact discipline (DEC-017): only handoff artifacts are auto-saved. Weights
are a handoff artifact (consumed by the live ``PortfolioConfig``), so
``refit_weights(save=True)`` persists them; reports (health report) stay
in-memory and are never auto-saved.

Parity: the composite series always comes from the Rust engine bindings
(research/live parity by construction); research-side weight *derivation*
mirrors the engine algorithm documented in
``src/alpha-core/src/strategies/combination/inverse_vol.rs`` (capped-simplex
projection with min 0.01 / max 0.5) so the reported weights agree with what
the engine actually used.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import alpha_core
import numpy as np
import pandas as pd

from quant_api.core.artifacts import write_weights
from quant_api.core.config import DataConfig, HarnessParams
from quant_api.core.data import close_volume, load_bars
from quant_api.core.pool import PoolEntry, load_pool
from quant_api.core.registry import Registry

#: Capped-simplex bounds for inverse-volatility weights, mirroring
#: ``InverseVol::default`` in src/alpha-core/src/strategies/combination/
#: inverse_vol.rs (DEFAULT_MIN_WEIGHT / DEFAULT_MAX_WEIGHT).
MIN_WEIGHT = 0.01
MAX_WEIGHT = 0.50

#: Feasibility tolerance and bisection steps used by the Rust projection
#: (FEASIBILITY_TOL / BISECT_STEPS); replicated for an exact mirror.
_FEASIBILITY_TOL = 1e-9
_BISECT_STEPS = 200

#: Default combine method for the health report and module entry points.
DEFAULT_COMBINE_METHOD = "inverse_vol"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_scores(series: list[float]) -> list[float]:
    """Forward-fill non-finite score values before any finite-only binding.

    Mirrors ``trading.portfolio._sanitize_scores`` (which mirrors the engine
    ``sanitize_scores`` in src/alpha-core/src/canonical/mapping.rs, see
    observation note OBS-011): leading non-finite values take the first
    finite value, interior ones carry the last finite value forward, and an
    all-non-finite series maps to zeros.
    """
    first = next((v for v in series if math.isfinite(v)), None)
    if first is None:
        return [0.0] * len(series)
    last = first
    out: list[float] = []
    for v in series:
        if math.isfinite(v):
            last = v
        out.append(last)
    return out


def _sample_stddev(series: list[float]) -> float | None:
    """Sample standard deviation (n-1 denominator), like the engine's
    ``sample_stddev``: ``None`` for series shorter than two observations or
    containing non-finite values ("no usable volatility estimate")."""
    n = len(series)
    if n < 2:
        return None
    mean = sum(series) / n
    if not math.isfinite(mean):
        return None
    variance = sum((x - mean) * (x - mean) for x in series) / (n - 1)
    if not math.isfinite(variance):
        return None
    return math.sqrt(variance)


def _capped_simplex(weights: list[float], eligible: list[int]) -> None:
    """Project the eligible weights onto the capped simplex
    ``{w : MIN_WEIGHT <= w_i <= MAX_WEIGHT, sum(w) = 1}``, in place.

    Exact Python mirror of ``InverseVol::apply_caps`` in
    src/alpha-core/src/strategies/combination/inverse_vol.rs (Component 4 -
    Combination): water-filling bisection over a global scale ``lambda`` so
    that the clipped weights sum to one, respecting both caps and the budget
    simultaneously. Single-survivor and infeasible-cap cases fall back the
    same way the engine does.
    """
    k = len(eligible)
    if k == 0:
        return
    if k == 1:
        # A single survivor must take the full budget even if that breaches
        # max_weight; sum-to-one always wins over the caps.
        weights[eligible[0]] = 1.0
        return
    lo, hi = MIN_WEIGHT, MAX_WEIGHT
    # Feasibility: the cap band must be able to absorb the full budget.
    if k * lo > 1.0 + _FEASIBILITY_TOL or k * hi < 1.0 - _FEASIBILITY_TOL:
        return  # keep the plain normalized weights
    scaled = [weights[i] for i in eligible]
    # Smallest normalized raw weight, guarded against underflow (mirrors
    # ``max(f64::MIN_POSITIVE)`` in the Rust fold).
    min_r = max(min(scaled), 2.2250738585072014e-308)
    low = 0.0
    high = hi / min_r
    if not math.isfinite(high):
        high = 1.7976931348623157e308  # f64::MAX
    for _ in range(_BISECT_STEPS):
        mid = 0.5 * (low + high)
        g = sum(max(lo, min(hi, r * mid)) for r in scaled)
        if g < 1.0:
            low = mid
        else:
            high = mid
    lam = 0.5 * (low + high)
    for i, r in zip(eligible, scaled):
        weights[i] = max(lo, min(hi, lam * r))


def _inverse_vol_weights(scores: list[list[float]]) -> list[float]:
    """Research-side inverse-volatility weights: ``w_i ∝ 1/std_i`` with the
    capped-simplex projection (min 0.01, max 0.5, sum 1).

    Mirrors ``InverseVol::compute_weights`` in
    src/alpha-core/src/strategies/combination/inverse_vol.rs exactly:
    zero/undefined-vol alphas get weight 0 and are excluded from the budget;
    an all-zero-vol pool falls back to equal weights; a lone alpha takes the
    full budget.
    """
    n = len(scores)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    raw = []
    for s in scores:
        vol = _sample_stddev(s)
        raw.append(1.0 / vol if vol is not None and vol > 0.0 else 0.0)
    eligible = [i for i, r in enumerate(raw) if r > 0.0]
    if not eligible:
        return [1.0 / n] * n
    raw_total = sum(raw[i] for i in eligible)
    weights = [0.0] * n
    for i in eligible:
        weights[i] = raw[i] / raw_total
    _capped_simplex(weights, eligible)
    return weights


def _score_pool(pool: list[PoolEntry], df: pd.DataFrame) -> dict[str, list[float]]:
    """Score every pool alpha over a bars frame in ONE engine batch call.

    Returns ``{alpha_id: sanitized_score_series}``; an empty pool yields {}.
    """
    expressions = [e.dsl for e in pool]
    if not expressions:
        return {}
    close, volume = close_volume(df)
    matrix = alpha_core.execute_batch_py(expressions, close, volume)
    return {
        e.alpha_id: _sanitize_scores(row)
        for e, row in zip(pool, matrix)
    }


def _simple_returns(close: list[float]) -> list[float]:
    """Per-bar simple close returns: ``r[0] = 0.0``, ``r[t] = c[t]/c[t-1] - 1``."""
    out = [0.0] * len(close)
    for t in range(1, len(close)):
        out[t] = close[t] / close[t - 1] - 1.0
    return out


def _daily_sums(ts: pd.Series, pnl: list[float]) -> tuple[list[object], list[float]]:
    """Aggregate per-bar PnL into per-UTC-date sums (sorted by date)."""
    daily: dict[object, float] = defaultdict(float)
    for t, p in zip(ts, pnl):
        daily[t.date()] += p
    dates = sorted(daily)
    return dates, [daily[d] for d in dates]


def _mean_ic(composite: list[float], rets: list[float], start: int) -> float:
    """Pearson correlation of composite score vs next-bar returns over the
    aligned finite pairs ``(composite[t], rets[t+1])`` with ``t >= start``.

    Computed with ``numpy.corrcoef`` per the health-report contract; 0.0 when
    fewer than two pairs exist or the correlation is undefined (constant
    series) - no usable signal.
    """
    xs: list[float] = []
    ys: list[float] = []
    for t in range(start, len(composite) - 1):
        c, r = composite[t], rets[t + 1]
        if math.isfinite(c) and math.isfinite(r):
            xs.append(c)
            ys.append(r)
    if len(xs) < 2:
        return 0.0
    corr = float(np.corrcoef(xs, ys)[0, 1])
    return corr if math.isfinite(corr) else 0.0


# ---------------------------------------------------------------------------
# combine_methods registry (Component 4 - Combination, DEC-017)
# ---------------------------------------------------------------------------

combine_methods = Registry("combine_methods")


def equal_weight(
    scores: list[list[float]], weights: list[float] | None = None
) -> list[float]:
    """Engine-backed equal-weight (or explicit-weight) combination.

    ``weights=None`` -> equal ``1/N`` weights; the weighted sum itself always
    runs in the Rust engine via ``alpha_core.composite_score_py`` (parity).
    """
    n = len(scores)
    ws = weights if weights is not None else [1.0 / n] * n
    return alpha_core.composite_score_py(scores, ws)


def inverse_vol(scores: list[list[float]]) -> list[float]:
    """Engine-backed inverse-volatility combination (Component 4 - Combination).

    Delegates to ``alpha_core.inverse_vol_combine_py``; the composite comes
    from the engine while the weights can be recovered research-side via
    ``_inverse_vol_weights`` (mirror of the same algorithm).
    """
    return alpha_core.inverse_vol_combine_py(scores)


combine_methods.register(
    "equal_weight",
    equal_weight,
    source="engine",
    description="equal 1/N (or explicit) weighted sum via composite_score_py",
)
combine_methods.register(
    "inverse_vol",
    inverse_vol,
    source="engine",
    description="inverse-volatility combination via inverse_vol_combine_py",
)

#: Method names whose research-side weights can be derived by this module.
_DERIVABLE_METHODS = ("equal_weight", "inverse_vol")


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def score_pool(
    pool: list[PoolEntry],
    data: DataConfig | None = None,
    harness: HarnessParams | None = None,
) -> dict[str, list[float]]:
    """Score every pool alpha's canonical DSL over the data (Component 4 -
    Combination input). ``data`` is a ``DataConfig`` (None = full history);
    all expressions run in ONE ``execute_batch_py`` call; each row is
    sanitized (forward-fill) so downstream finite-only bindings accept it.
    ``harness`` is accepted for signature symmetry with the health report and
    unused here. Returns ``{alpha_id: score_series}``.
    """
    df = load_bars(data)
    return _score_pool(pool, df)


def pool_pnl(
    pool: list[PoolEntry],
    data: DataConfig | None = None,
    harness: HarnessParams | None = None,
) -> dict[str, list[float]]:
    """Canonical per-bar NET PnL for every pool alpha (Component 1 pipeline:
    batch score -> sanitize -> canonical position -> net PnL).

    This is the canonical input for ``orthogonalize`` (Component 3 -
    Orthogonalization contract: "candidate plus pool PnLs"; reconciliation
    note REC-008). ``data``/``harness`` resolve like the rest of the API.
    """
    h = harness or HarnessParams()
    df = load_bars(data)
    close, volume = close_volume(df)
    rets = _simple_returns(close)
    expressions = [e.dsl for e in pool]
    matrix = alpha_core.execute_batch_py(expressions, close, volume)
    out: dict[str, list[float]] = {}
    for entry, row in zip(pool, matrix):
        sane = _sanitize_scores(row)
        position = alpha_core.canonical_map_py(
            sane,
            span=h.span,
            z_window=h.z_window,
            band=h.band,
            cap=h.cap,
            bars_per_day=h.bars_per_day,
        ).position
        out[entry.alpha_id] = alpha_core.compute_pnl_py(
            position, rets, h.cost_per_side, h.bars_per_day
        ).net
    return out


def orthogonalize(
    candidate: list[float],
    pool: list[list[float]],
    min_residual_sharpe: float = 0.0,
) -> dict:
    """Component 3 - Orthogonalization verdict for one candidate vs a pool.

    Canonical input is per-bar NET PNL series (reconciliation note REC-008):
    ``orthogonalize_py(candidate, pool)`` regresses the candidate PnL on the
    pool PnLs (OLS through the origin); the residual's ANNUALIZED Sharpe
    (daily-aggregated residual, engine ``sharpe_py``) decides the verdict:
    "INCREMENTAL" when the finite Sharpe > ``min_residual_sharpe``, else
    "REDUNDANT". Use ``pool_pnl`` to build the series from a pool folder.
    The canon pass bar (residual Sharpe 0.3-0.5 / t-stat > 2, walk-forward
    split) is phase-2; ``min_residual_sharpe`` defaults to 0.0 (admission
    sign test) until then.

    Returns the full dossier: residual series, OLS betas (Python mirror of
    the engine regression), r-squared, verdict and note.
    """
    residual = alpha_core.orthogonalize_py(candidate, pool)
    bpd = HarnessParams().bars_per_day
    daily = [sum(residual[i : i + bpd]) for i in range(0, len(residual), bpd)]
    residual_sharpe = alpha_core.sharpe_py(daily, bpd)
    y = np.asarray(candidate, dtype=float)
    x = np.asarray(pool, dtype=float).T
    betas = np.linalg.lstsq(x, y, rcond=None)[0]
    resid = y - x @ betas
    denom = float(((y - y.mean()) ** 2).sum())
    r_squared = 1.0 - float((resid**2).sum()) / denom if denom > 0.0 else 0.0
    verdict = (
        "INCREMENTAL"
        if math.isfinite(residual_sharpe) and residual_sharpe > min_residual_sharpe
        else "REDUNDANT"
    )
    note = (
        f"residual annualized Sharpe {residual_sharpe:.3f} > {min_residual_sharpe};"
        " candidate is additive to the pool"
        if verdict == "INCREMENTAL"
        else f"residual annualized Sharpe {residual_sharpe:.3f} <= {min_residual_sharpe};"
        " candidate is redundant to the pool"
    )
    return {
        "residual_sharpe": residual_sharpe,
        "residual": list(residual),
        "betas": [float(b) for b in betas],
        "r_squared": r_squared,
        "verdict": verdict,
        "note": note,
    }


def _standardize(matrix: list[list[float]]) -> list[list[float]]:
    """Row-wise z-score (canon stage-4-combination section 2: weights are a
    risk-budget allocation applied to STANDARDIZED scores, undistorted by
    each alpha's native scale). Zero-variance rows map to zeros."""
    out: list[list[float]] = []
    for row in matrix:
        arr = np.asarray(row, dtype=float)
        std = float(arr.std())
        if not math.isfinite(std) or std == 0.0:
            out.append([0.0] * len(row))
            continue
        mean = float(arr.mean())
        out.append([(v - mean) / std for v in row])
    return out


def combine(
    scores: dict[str, list[float]] | list[list[float]],
    method: str = DEFAULT_COMBINE_METHOD,
    weights: list[float] | None = None,
    data: DataConfig | None = None,
) -> dict:
    """Combine score series into a composite (Component 4 - Combination).

    ``scores`` is either ``{alpha_id: series}`` or a plain list of series
    (keys become the indices). Per the canon (stage-4 section 2, reconciliation
    note REC-009), the engine defaults combine STANDARDIZED rows: equal_weight
    -> 1/N or the given weights; inverse_vol -> weights from the capped-simplex
    of ``1/std`` of the RAW series (the risk measure), applied to the
    standardized rows via the engine ``composite_score_py`` (research/live
    parity; the engine's raw-input ``inverse_vol_combine_py`` remains for the
    parity suite). ``data`` is reserved for future alignment and unused.
    Returns ``{"composite", "weights", "method", "provenance"}`` where
    ``provenance = {"method", "source"}`` with source "engine" for the
    defaults or "python" for registered research methods. ``weights`` is a
    dict for the engine defaults and ``None`` for custom research methods
    (their implicit weights are unrecoverable).
    """
    if isinstance(scores, dict):
        keys: list[Any] = sorted(scores)
        matrix = [list(scores[k]) for k in keys]
    else:
        matrix = [list(s) for s in scores]
        keys = list(range(len(matrix)))
    if not matrix:
        raise ValueError("scores must be non-empty")
    n_bars = len(matrix[0])
    if n_bars == 0:
        raise ValueError("score series must be non-empty")
    if any(len(s) != n_bars for s in matrix):
        raise ValueError("all score series must have equal length")

    method_entry = combine_methods.get(method)
    if method == "equal_weight":
        if weights is not None:
            if len(weights) != len(matrix):
                raise ValueError(
                    f"weights must have one value per series (got {len(weights)} "
                    f"for {len(matrix)} series)"
                )
            derived = list(weights)
        else:
            derived = [1.0 / len(matrix)] * len(matrix)
        composite = alpha_core.composite_score_py(_standardize(matrix), derived)
    elif method == "inverse_vol":
        if weights is not None:
            raise ValueError(
                "weights are derived for inverse_vol (capped-simplex of 1/std); "
                "passing explicit weights is not supported"
            )
        derived = _inverse_vol_weights(matrix)
        composite = alpha_core.composite_score_py(_standardize(matrix), derived)
    else:
        # Custom research method: raw input, no derivation rule for its weights.
        if weights is not None:
            raise ValueError(
                f"weights are only honored by equal_weight (got method={method!r})"
            )
        composite = method_entry.fn(matrix)
        derived = None  # custom research methods: implicit weights unrecoverable

    return {
        "composite": composite,
        "weights": (
            {k: w for k, w in zip(keys, derived)} if derived is not None else None
        ),
        "method": method,
        "provenance": {"method": method, "source": method_entry.source},
    }


def refit_weights(
    pool: list[PoolEntry],
    data: DataConfig | None = None,
    method: str = DEFAULT_COMBINE_METHOD,
    window_days: int | None = None,
    save: bool = True,
    root=None,
) -> dict:
    """Weekly weight-refit cadence (Component 4 - Combination, DEC-017).

    Scores the pool over the data (``window_days=None`` = full history;
    ``window_days=N`` = bars of the last N calendar days), then derives the
    weights: equal_weight -> ``1/n``; inverse_vol -> capped-simplex of
    ``1/std`` (mirror of inverse_vol.rs). Returns
    ``{"generated": ISO date, "method", "weights": {alpha_id: w},
    "provenance": {"method", "source"}}``. With ``save=True`` the result is
    persisted via ``quant_api.core.artifacts.write_weights`` to
    ``root/weights.json`` (default root ``data/pool``) - the handoff artifact
    consumed by the live ``PortfolioConfig``.
    """
    if not pool:
        raise ValueError("pool must be non-empty")
    if window_days is not None and (not isinstance(window_days, int) or window_days <= 0):
        raise ValueError(f"window_days must be None or a positive int (got {window_days!r})")
    method_entry = combine_methods.get(method)
    if method not in _DERIVABLE_METHODS:
        raise ValueError(
            f"refit_weights derives weights only for {sorted(_DERIVABLE_METHODS)} "
            f"(got method={method!r}); custom methods have no research-side "
            "derivation rule"
        )

    df = load_bars(data)
    if window_days is not None:
        cutoff = df["ts"].max() - pd.Timedelta(days=window_days)
        df = df[df["ts"] >= cutoff].reset_index(drop=True)
    scores = _score_pool(pool, df)
    ids = sorted(scores)
    matrix = [scores[i] for i in ids]

    if method == "inverse_vol":
        derived = _inverse_vol_weights(matrix)
    else:  # equal_weight
        derived = [1.0 / len(ids)] * len(ids)

    result = {
        "generated": date.today().isoformat(),
        "method": method,
        "weights": {a: w for a, w in zip(ids, derived)},
        "provenance": {"method": method, "source": method_entry.source},
    }
    if save:
        write_weights(result, root=root)
    return result


def portfolio_health_report(
    pool: list[PoolEntry],
    data: DataConfig | None = None,
    harness: HarnessParams | None = None,
    window_days: int = 30,
) -> dict:
    """Monthly allocation-review input (Component 4 - Combination); in-memory
    only, never auto-saved (DEC-017 artifact discipline).

    Pipeline: ``score_pool`` (one engine batch) -> ``combine`` (inverse_vol)
    -> ``canonical_map_py`` position -> ``compute_pnl_py`` net per-bar PnL ->
    daily sums. Metrics:

    - ``full_sample_sharpe``: annualized Sharpe of the daily net PnL
      (``sharpe_py``, daily series).
    - ``max_drawdown``: most negative peak-to-trough drawdown of the daily
      equity curve (``max_drawdown_py``).
    - ``last_window_sharpe``: same Sharpe over the last ``window_days``
      calendar days of bars.
    - ``window_return``: sum of daily net PnL over the same last
      ``window_days`` calendar days (window-consistent with the Sharpe).
    - ``rolling_mean_ic``: numpy corrcoef of the composite vs next-bar
      returns over the last window's aligned finite pairs (0.0 when
      undefined).

    Verdict: "refit" when ``last_window_sharpe < 0`` or
    ``rolling_mean_ic < 0.05``, else "ok".
    """
    if not pool:
        raise ValueError("pool must be non-empty")
    if not isinstance(window_days, int) or window_days <= 0:
        raise ValueError(f"window_days must be a positive int (got {window_days!r})")
    h = harness or HarnessParams()

    df = load_bars(data)
    scores = _score_pool(pool, df)
    ids = sorted(scores)
    matrix = [scores[i] for i in ids]
    composite = combine(matrix, method=DEFAULT_COMBINE_METHOD)["composite"]

    close, _ = close_volume(df)
    rets = _simple_returns(close)
    position = alpha_core.canonical_map_py(
        composite,
        span=h.span,
        z_window=h.z_window,
        band=h.band,
        cap=h.cap,
        bars_per_day=h.bars_per_day,
    ).position
    net = alpha_core.compute_pnl_py(
        position, rets, h.cost_per_side, h.bars_per_day
    ).net

    dates, daily_pnl = _daily_sums(df["ts"], net)
    full_sample_sharpe = alpha_core.sharpe_py(daily_pnl, h.bars_per_day)
    max_drawdown = alpha_core.max_drawdown_py(daily_pnl)

    last_date = dates[-1]
    window_cutoff = last_date - timedelta(days=window_days)
    window_pnl = [p for d, p in zip(dates, daily_pnl) if d >= window_cutoff]
    last_window_sharpe = alpha_core.sharpe_py(window_pnl, h.bars_per_day)
    window_return = sum(window_pnl)

    # Rolling (trailing) window of bars for the IC; the score must sit inside
    # the window, the next-bar return may be the first bar after it.
    ts_cutoff = df["ts"].max() - pd.Timedelta(days=window_days)
    start = int((df["ts"] >= ts_cutoff).idxmax()) if (df["ts"] >= ts_cutoff).any() else 0
    rolling_mean_ic = _mean_ic(composite, rets, start)

    verdict = "refit" if (last_window_sharpe < 0.0 or rolling_mean_ic < 0.05) else "ok"

    return {
        "generated": pd.Timestamp.now(tz="UTC").isoformat(),
        "pool_size": len(ids),
        "bars": len(df),
        "window_days": window_days,
        "full_sample_sharpe": full_sample_sharpe,
        "max_drawdown": max_drawdown,
        "last_window_sharpe": last_window_sharpe,
        "window_return": window_return,
        "rolling_mean_ic": rolling_mean_ic,
        "verdict": verdict,
        "units": "PnL metrics are in canonical composite units (position x"
        " return per bar, NOT capital fractions); sharpe/IC are scale-free",
    }


# ``load_pool`` is a public-surface re-export of quant_api.core.pool.load_pool
# (already imported at the top of this module).
__all__ = [
    "combine_methods",
    "combine",
    "equal_weight",
    "inverse_vol",
    "load_pool",
    "orthogonalize",
    "score_pool",
    "portfolio_health_report",
    "refit_weights",
]
