"""quantcore.portfolio - Portfolio Researcher module."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import alpha_core
import numpy as np
import pandas as pd

from core.artifacts import AlphaPool, Composite, WeightsArtifact
from core.contracts import HarnessParams, Instrument
from core.data import BarFrame
from core.signal import close_returns
from core.registry import Registry

__all__ = [
    "OrthoReport",
    "PortfolioHealth",
    "combine",
    "combine_methods",
    "equal_weight",
    "health_report",
    "inverse_vol",
    "orthogonalize",
    "refit_weights",
    "score_pool",
]

#: Capped-simplex bounds for inverse-volatility weights, mirroring
#: ``InverseVol::default`` in src/alpha-core/src/strategies/combination/
#: inverse_vol.rs (DEFAULT_MIN_WEIGHT / DEFAULT_MAX_WEIGHT).
MIN_WEIGHT = 0.01
MAX_WEIGHT = 0.50

#: Feasibility tolerance and bisection steps used by the Rust projection
#: (FEASIBILITY_TOL / BISECT_STEPS); replicated for an exact mirror.
_FEASIBILITY_TOL = 1e-9
_BISECT_STEPS = 200

#: Default combine method for the module entry points.
DEFAULT_COMBINE_METHOD = "inverse_vol"

#: Trailing calendar window (days) for the health report's last-window
#: statistics.
DEFAULT_HEALTH_WINDOW_DAYS = 30

#: Composite must beat this mean IC over the health window, else verdict
#: "refit".
MIN_HEALTH_MEAN_IC = 0.05


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def _sample_stddev(series: list[float]) -> float | None:
    """Sample standard deviation (n-1 denominator) — PARITY-LOCKED with the
    engine's ``sample_stddev``: ANY non-finite entry (raw rows carry warmup
    NaN) poisons the mean and returns ``None`` ("no usable volatility
    estimate" -> zero weight). Do not switch to finite-only statistics
    without re-recording the goldens: finite-only changes which alphas are
    eligible and therefore every downstream weight."""
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
    src/alpha-core/src/strategies/combination/inverse_vol.rs: water-filling
    bisection over a global scale ``lambda`` so that the clipped weights sum
    to one, respecting both caps and the budget simultaneously. Single-
    survivor and infeasible-cap cases fall back the same way the engine
    does.
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
    """Research-side inverse-volatility weights: ``w_i = 1/std_i`` with the
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


def _standardize(matrix: list[list[float]]) -> list[list[float]]:
    """Row-wise z-score — PARITY-LOCKED semantics (same computation as the
    pre-redesign implementation): the std runs over the WHOLE row including
    warmup NaN, so any non-finite entry makes the row's std non-finite and
    the ENTIRE row maps to zeros. This degenerate-on-warmup behavior is what
    every recorded system output was produced with; do not "fix" it without
    re-recording the goldens."""
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


def _as_matrix(scores: dict[str, np.ndarray]) -> tuple[list[str], list[list[float]]]:
    """Sorted alpha ids + row matrix (Python floats) from a score mapping."""
    keys = sorted(scores)
    return keys, [[float(v) for v in scores[k]] for k in keys]




def _daily_sums(ts: pd.DatetimeIndex, pnl: list[float]) -> tuple[list[object], list[float]]:
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


def _instrument_for(bars: BarFrame) -> Instrument:
    """Resolve the bar window's instrument (bare symbol from the id)."""
    symbol = bars.instrument_id.split(".", 1)[0]
    return Instrument.load(symbol)


# ---------------------------------------------------------------------------
# combine_methods registry
# ---------------------------------------------------------------------------

combine_methods = Registry("combine_methods")


def equal_weight(scores: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, float]]:
    """Engine-backed equal-weight combination (``1/N``).

    The weighted sum itself always runs in the Rust engine via
    ``alpha_core.composite_score_py`` over the standardized rows (parity).

    Parameters
    ----------
    scores : dict[str, numpy.ndarray]
        Mapping alpha_id -> raw score series (z-units; non-finite entries
        allowed and handled by standardization).

    Returns
    -------
    tuple[numpy.ndarray, dict[str, float]]
        ``(composite, weights)`` - composite in z-units, equal fractions
        per alpha_id (sum 1).
    """
    keys, matrix = _as_matrix(scores)
    derived = [1.0 / len(matrix)] * len(matrix)
    composite = alpha_core.composite_score_py(_standardize(matrix), derived)
    return np.asarray(composite, dtype=float), dict(zip(keys, derived))


def inverse_vol(scores: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, float]]:
    """Engine-mirrored inverse-volatility combination — PARITY-LOCKED.

    Identical call sequence to the pre-redesign implementation: weights are
    the capped-simplex of ``1/std`` over the RAW rows (``_sample_stddev``
    carries the engine's NaN-poisoning semantics: one non-finite entry means
    no volatility estimate and zero weight), the composite is the engine
    ``composite_score_py`` over the standardized rows.

    Parameters
    ----------
    scores : dict[str, numpy.ndarray]
        Mapping alpha_id -> raw score series.

    Returns
    -------
    tuple[numpy.ndarray, dict[str, float]]
        ``(composite, weights)`` - composite in z-units, fractions per
        alpha_id (sum 1).
    """
    keys, matrix = _as_matrix(scores)
    derived = _inverse_vol_weights(matrix)
    composite = alpha_core.composite_score_py(_standardize(matrix), derived)
    return np.asarray(composite, dtype=float), dict(zip(keys, derived))


if "equal_weight" not in combine_methods.names():
    combine_methods.register(
        "equal_weight",
        equal_weight,
        source="engine",
        description="equal 1/N weighted sum via composite_score_py over standardized rows",
    )
if "inverse_vol" not in combine_methods.names():
    combine_methods.register(
        "inverse_vol",
        inverse_vol,
        source="engine",
        description="inverse-volatility combination: capped-simplex 1/std weights"
        " applied to standardized rows via composite_score_py",
    )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def score_pool(pool: AlphaPool, bars: BarFrame) -> dict[str, np.ndarray]:
    """Score every pool alpha's canonical DSL over the bars (combination
    input).

    All expressions run in ONE ``execute_batch_py`` call. Rows are returned
    RAW (engine contract: the first ``window - 1`` bars of each rolling
    operator are NaN) so the combination sees exactly what the canonical
    harness sees; ``combine`` standardizes internally. Callers must not
    forward-fill here — sanitizing changes vol estimates and therefore the
    combination weights.

    Parameters
    ----------
    pool : AlphaPool
        The research pool (entries carry ``dsl``).
    bars : BarFrame
        The bar window to score over.

    Returns
    -------
    dict[str, numpy.ndarray]
        ``{alpha_id: raw score series}`` (z-units); an empty pool
        yields ``{}``.
    """
    expressions = [e.dsl for e in pool.entries]
    if not expressions:
        return {}
    close = bars.close_list()
    volume = bars.volume_list()
    matrix = alpha_core.execute_batch_py(expressions, close, volume)
    return {
        entry.alpha_id: np.asarray(row, dtype=float)
        for entry, row in zip(pool.entries, matrix)
    }


def combine(
    scores: dict[str, np.ndarray],
    method: str = DEFAULT_COMBINE_METHOD,
    weights: dict[str, float] | None = None,
    *,
    window,
) -> Composite:
    """Combine per-alpha score series into one composite (z-units).

    Built-ins dispatch through the ``combine_methods`` registry (real
    dispatch: replacing a registration changes this function's output).
    Explicit ``weights`` bypass the method entirely (the composite's
    ``method`` is recorded as ``"explicit"``); they are normalized to sum
    to one, exactly like the engine does inside ``composite_score_py``, and
    applied to the standardized rows.

    Parameters
    ----------
    scores : dict[str, numpy.ndarray]
        Mapping alpha_id -> score series (z-units), all equal length.
    method : str
        Registry key in ``combine_methods``. Built-ins: ``"equal_weight"``,
        ``"inverse_vol"``.
    weights : dict[str, float] | None
        Explicit per-alpha weights (fractions); overrides ``method`` when
        given.
    window : core.artifacts.Window
        The bar window the scores are aligned to; recorded on the Composite
        so downstream consumers (risk) can validate provenance.

    Returns
    -------
    Composite
        Frozen artifact: alpha_ids, normalized weights, composite scores,
        window, method label.

    Raises
    ------
    ValueError
        Empty/ragged scores, unknown method, explicit weights that do not
        cover exactly the alpha ids, a zero/non-finite explicit weight sum,
        or a registered method returning a malformed result.
    """
    if not scores:
        raise ValueError("scores must be non-empty")
    keys = sorted(scores)
    n_bars = len(scores[keys[0]])
    if n_bars == 0:
        raise ValueError("score series must be non-empty")
    if any(len(scores[k]) != n_bars for k in keys):
        raise ValueError("all score series must have equal length")

    if weights is not None:
        missing = [k for k in keys if k not in weights]
        extra = [k for k in sorted(weights) if k not in set(keys)]
        if missing or extra:
            raise ValueError(
                "explicit weights must cover exactly the score keys"
                f" (missing {missing}, unknown {extra})"
            )
        raw = [float(weights[k]) for k in keys]
        total = math.fsum(raw)
        if not math.isfinite(total) or total == 0.0:
            raise ValueError(
                f"explicit weights must sum to a non-zero finite value (got {total!r})"
            )
        derived = [w / total for w in raw]
        composite = alpha_core.composite_score_py(_standardize([list(scores[k]) for k in keys]), derived)
        method_label = "explicit"
    else:
        try:
            composite_list, derived_dict = combine_methods.call(method, scores)
        except KeyError as exc:
            raise ValueError(str(exc)) from None
        composite = list(composite_list)
        if len(composite) != n_bars:
            raise ValueError(
                f"combine method {method!r} returned {len(composite)} values "
                f"for {n_bars} bars"
            )
        if not all(math.isfinite(value) for value in composite):
            raise ValueError(f"combine method {method!r} returned non-finite values")
        missing = [k for k in keys if k not in derived_dict]
        if missing:
            raise ValueError(
                f"combine method {method!r} returned no weights for {missing}"
            )
        derived = [float(derived_dict[k]) for k in keys]
        method_label = method

    return Composite(
        alpha_ids=tuple(keys),
        weights=tuple(derived),
        scores=np.asarray(composite, dtype=float),
        window=window,
        method=method_label,
    )


@dataclass(frozen=True)
class OrthoReport:
    """Component-3 orthogonalization verdict for one candidate vs a pool.

    Parameters
    ----------
    residual_sharpe : float
        Annualized Sharpe of the residual PnL (daily-aggregated, engine
        ``sharpe_py``).
    residual : list[float]
        The residual series (candidate minus pool projection).
    betas : list[float]
        OLS betas of the candidate on the pool series (through the origin
        in the engine regression; full-ols mirror here), pool order =
        sorted alpha ids.
    r_squared : float
        Share of candidate variance explained by the pool (0.0 when the
        candidate is constant).
    verdict : str
        ``"INCREMENTAL"`` when the finite residual Sharpe exceeds
        ``min_residual_sharpe``, else ``"REDUNDANT"``.
    note : str
        Human-readable one-line rationale.
    """

    residual_sharpe: float
    residual: list[float]
    betas: list[float]
    r_squared: float
    verdict: str
    note: str


@dataclass(frozen=True)
class PortfolioHealth:
    """Monthly allocation-review input (in-memory only, never auto-saved).

    Parameters
    ----------
    generated : str
        ISO-8601 UTC timestamp of the report.
    pool_size : int
        Number of alphas in the composite.
    bars : int
        Number of bars in the window.
    window_days : int
        Trailing calendar window for the last-window statistics.
    full_sample_sharpe : float
        Annualized Sharpe of the daily net PnL (full sample).
    max_drawdown : float
        Most negative peak-to-trough drawdown of the daily equity curve.
    last_window_sharpe : float
        Sharpe over the last ``window_days`` calendar days of bars.
    window_return : float
        Sum of daily net PnL over the same window.
    rolling_mean_ic : float
        Pearson correlation of the composite vs next-bar returns over the
        last window's aligned finite pairs (0.0 when undefined).
    verdict : str
        ``"refit"`` when ``last_window_sharpe < 0`` or
        ``rolling_mean_ic < 0.05``, else ``"ok"``.
    units : str
        Units note: PnL metrics are in canonical composite units (position
        x return per bar, NOT capital fractions); sharpe/IC are scale-free.
    """

    generated: str
    pool_size: int
    bars: int
    window_days: int
    full_sample_sharpe: float
    max_drawdown: float
    last_window_sharpe: float
    window_return: float
    rolling_mean_ic: float
    verdict: str
    units: str


def orthogonalize(
    candidate: np.ndarray,
    scores: dict[str, np.ndarray],
    min_residual_sharpe: float = 0.0,
) -> OrthoReport:
    """Orthogonalization verdict for one candidate vs a pool of series.

    The canonical input is per-bar NET PnL series (candidate + pool): build
    them with the canonical pipeline (batch score -> sanitize ->
    ``canonical_map_py`` -> ``compute_pnl_py``). ``orthogonalize_py``
    regresses the candidate on the pool series; the residual's ANNUALIZED
    Sharpe (daily-aggregated residual, engine ``sharpe_py``) decides the
    verdict: ``"INCREMENTAL"`` when the finite Sharpe >
    ``min_residual_sharpe``, else ``"REDUNDANT"``. The admission bar
    ``min_residual_sharpe`` defaults to 0.0 (sign test).

    Parameters
    ----------
    candidate : numpy.ndarray
        Candidate series (per-bar net PnL is the canonical choice).
    scores : dict[str, numpy.ndarray]
        Pool series keyed by alpha_id; regression order = sorted ids.
    min_residual_sharpe : float
        Admission threshold for the residual Sharpe.

    Returns
    -------
    OrthoReport
        Residual Sharpe, residual series, OLS betas (Python mirror of the
        engine regression), r-squared, verdict and note.
    """
    candidate_list = [float(v) for v in candidate]
    keys, pool = _as_matrix(scores)
    residual = alpha_core.orthogonalize_py(candidate_list, pool)
    bpd = HarnessParams().bars_per_day
    daily = [sum(residual[i : i + bpd]) for i in range(0, len(residual), bpd)]
    residual_sharpe = alpha_core.sharpe_py(daily, bpd)
    y = np.asarray(candidate_list, dtype=float)
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
    return OrthoReport(
        residual_sharpe=residual_sharpe,
        residual=[float(v) for v in residual],
        betas=[float(b) for b in betas],
        r_squared=r_squared,
        verdict=verdict,
        note=note,
    )


def refit_weights(
    pool: AlphaPool,
    bars: BarFrame,
    method: str = DEFAULT_COMBINE_METHOD,
) -> WeightsArtifact:
    """Weight-refit cadence: derive pool weights over the bars window.

    Scores the pool (one engine batch, raw rows) and resolves the weights
    through the ``combine_methods`` registry (real dispatch), so every
    registered method's contract ``fn(scores) -> (composite, weights)``
    applies. Returns the unsaved artifact - SAVING is the caller's explicit
    ``WeightsArtifact.save()`` (the handoff artifact consumed by the live
    ``PortfolioConfig``).

    Parameters
    ----------
    pool : AlphaPool
        The research pool (non-empty).
    bars : BarFrame
        The refit window (full window; slice the BarFrame for a trailing
        refit).
    method : str
        Registry key in ``combine_methods``.

    Returns
    -------
    WeightsArtifact
        ``generated`` (ISO date), ``method``, ``weights`` (fractions per
        alpha_id), ``window``.

    Raises
    ------
    ValueError
        Empty pool or unknown method.
    """
    if not pool.entries:
        raise ValueError("pool must be non-empty")
    scores = score_pool(pool, bars)
    try:
        _, derived = combine_methods.call(method, scores)
    except KeyError as exc:
        raise ValueError(str(exc)) from None
    return WeightsArtifact(
        generated=date.today().isoformat(),
        method=method,
        weights={k: float(derived[k]) for k in sorted(derived)},
        window=bars.window,
    )


def health_report(composite: Composite, bars: BarFrame) -> PortfolioHealth:
    """Monthly allocation-review input; in-memory only, never auto-saved.

    Pipeline: composite scores -> ``canonical_map_py`` position ->
    ``compute_pnl_py`` net per-bar PnL (cost = the bar instrument's cost
    model) -> daily sums. Metrics:

    - ``full_sample_sharpe``: annualized Sharpe of the daily net PnL.
    - ``max_drawdown``: most negative peak-to-trough drawdown of the daily
      equity curve.
    - ``last_window_sharpe``: same Sharpe over the last 30 calendar days of
      bars.
    - ``window_return``: sum of daily net PnL over the same window.
    - ``rolling_mean_ic``: numpy corrcoef of the composite vs next-bar
      returns over the last window's aligned finite pairs (0.0 when
      undefined).

    Verdict: ``"refit"`` when ``last_window_sharpe < 0`` or
    ``rolling_mean_ic < 0.05``, else ``"ok"``.

    Parameters
    ----------
    composite : Composite
        The combined composite (scores aligned to ``bars``).
    bars : BarFrame
        The bar window (close feeds returns; instrument feeds the cost
        model).

    Returns
    -------
    PortfolioHealth
        Frozen report (see the dataclass docstring for field semantics).

    Raises
    ------
    ValueError
        Composite score length differs from the bar count.
    """
    window_days = DEFAULT_HEALTH_WINDOW_DAYS
    composite_list = [float(v) for v in composite.scores]
    close = bars.close_list()
    n = len(close)
    if len(composite_list) != n:
        raise ValueError(
            f"composite length {len(composite_list)} != data bars {n};"
            " composite must be aligned with the data window"
        )
    h = HarnessParams()
    instrument = _instrument_for(bars)
    cost_per_side = instrument.cost.cost_per_side_frac

    rets = close_returns(close)
    position = alpha_core.canonical_map_py(
        composite_list,
        span=h.span,
        z_window=h.z_window,
        band=h.band,
        cap=h.cap,
        bars_per_day=h.bars_per_day,
    ).position
    net = alpha_core.compute_pnl_py(position, rets, cost_per_side, h.bars_per_day).net

    dates, daily_pnl = _daily_sums(bars.ts, net)
    full_sample_sharpe = alpha_core.sharpe_py(daily_pnl, h.bars_per_day)
    max_drawdown = alpha_core.max_drawdown_py(daily_pnl)

    last_date = dates[-1]
    window_cutoff = last_date - timedelta(days=window_days)
    window_pnl = [p for d, p in zip(dates, daily_pnl) if d >= window_cutoff]
    last_window_sharpe = alpha_core.sharpe_py(window_pnl, h.bars_per_day)
    window_return = sum(window_pnl)

    # Rolling (trailing) window of bars for the IC; the score must sit
    # inside the window, the next-bar return may be the first bar after it.
    ts_cutoff = bars.ts.max() - pd.Timedelta(days=window_days)
    mask = np.asarray(bars.ts >= ts_cutoff)
    start = int(np.argmax(mask)) if bool(mask.any()) else 0
    rolling_mean_ic = _mean_ic(composite_list, rets, start)

    verdict = (
        "refit" if (last_window_sharpe < 0.0 or rolling_mean_ic < MIN_HEALTH_MEAN_IC) else "ok"
    )

    return PortfolioHealth(
        generated=pd.Timestamp.now(tz="UTC").isoformat(),
        pool_size=len(composite.alpha_ids),
        bars=n,
        window_days=window_days,
        full_sample_sharpe=full_sample_sharpe,
        max_drawdown=max_drawdown,
        last_window_sharpe=last_window_sharpe,
        window_return=window_return,
        rolling_mean_ic=rolling_mean_ic,
        verdict=verdict,
        units="PnL metrics are in canonical composite units (position x"
        " return per bar, NOT capital fractions); sharpe/IC are scale-free",
    )
