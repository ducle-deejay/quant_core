"""quantcore.alpha - Quantitative Researcher module."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date

import alpha_core
import numpy as np
import pandas as pd

from core.artifacts import (
    AlphaPool,
    PoolEntry,
    SpecSheet,
    TearSheet,
    append_trial_ledger,
)
from core.contracts import HarnessParams, Instrument
from core.data import BarFrame
from core.signal import close_returns, sanitize_scores
from core.registry import Registry

__all__ = [
    "AlphaConfig",
    "EngineQuantitativeModel",
    "GateCriteria",
    "ScreenResult",
    "build_spec_sheet",
    "deliver",
    "evaluate_seed",
    "ga_fitness",
    "mine_seeds",
    "quantitative_models",
    "score",
    "score_model",
    "screen_batch",
    "validate_seed",
]


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GateCriteria:
    """Evaluation/screening gate thresholds for one alpha.

    Phase gate: absolute Information Coefficient, cost drag, net Sharpe,
    walk-forward stability, ICIR. ``sharpe_variance`` feeds the
    deflated-Sharpe threshold when ``AlphaConfig.n_trials > 0``.

    Parameters
    ----------
    min_abs_ic : float
        Minimum absolute mean IC (rank correlation, z-units vs returns).
    max_cost_drag_pct : float
        Maximum cost drag in percent (40.0 == 40%).
    min_net_sharpe : float
        Minimum annualized net Sharpe of the daily PnL.
    min_icir : float
        Minimum IC information ratio (mean/std of per-block rank ICs).
    min_positive_blocks_pct : float
        Minimum share of positive walk-forward blocks in percent.
    ic_horizons : tuple[int, ...]
        IC ladder horizons in bars.
    ic_window : int
        Block length in bars for the ICIR and IC estimation windows.
    walk_forward_block_days : int
        Walk-forward block length in trading days.
    ann_factor : float
        Annualization factor for daily-observation statistics.
    bars_per_day : int
        Bars per trading day used to aggregate daily statistics.
    sharpe_variance : float
        Trial-Sharpe variance used by the deflated threshold.
    """

    min_abs_ic: float = 0.02
    max_cost_drag_pct: float = 40.0
    min_net_sharpe: float = 0.8
    min_icir: float = 0.3
    min_positive_blocks_pct: float = 60.0
    ic_horizons: tuple[int, ...] = (1, 5, 15)
    ic_window: int = 480
    walk_forward_block_days: int = 5
    ann_factor: float = 250.0  # daily-observation annualization
    bars_per_day: int = 240
    sharpe_variance: float = 0.25  # trial-Sharpe variance for deflation


@dataclass(frozen=True)
class AlphaConfig:
    """Everything one research call needs; every field has a default.

    Parameters
    ----------
    harness : HarnessParams
        Canonical simulation parameters (span, z_window, band, cap,
        bars_per_day).
    gate : GateCriteria
        Evaluation/screening thresholds.
    ga_population_size : int
        GA population size used by ``mine_seeds``.
    ga_generations : int
        GA generation count used by ``mine_seeds``.
    ga_seed : int
        GA RNG seed (deterministic breeding for a fixed seed).
    n_trials : int
        Effective trial count; ``> 0`` wires the deflated-Sharpe check into
        the gate. Trial counting is the caller's responsibility (use
        ``record_trial=True`` so the ledger stays complete).
    record_trial : bool
        When True, every evaluation is appended to the trial ledger
        (``core.artifacts.append_trial_ledger``).
    """

    harness: HarnessParams = field(default_factory=HarnessParams)
    gate: GateCriteria = field(default_factory=GateCriteria)
    ga_population_size: int = 100
    ga_generations: int = 20
    ga_seed: int = 42
    n_trials: int = 0
    record_trial: bool = False


@dataclass(frozen=True)
class ScreenResult:
    """Batch screening output.

    Parameters
    ----------
    funnel : dict
        Counts: ``total_candidates``, ``ic_pass_count``,
        ``drag_pass_count`` (engine screening gates) and
        ``survivor_count`` (full-gate verdict IN).
    tear_sheets : list[TearSheet]
        One tear sheet per candidate, in input order.
    survivors : list[str]
        Canonical DSL strings of the full-gate survivors (verdict IN).
    """

    funnel: dict
    tear_sheets: list[TearSheet]
    survivors: list[str]


# --------------------------------------------------------------------------- #
# Extension registries
# --------------------------------------------------------------------------- #

#: GA fitness slot: engine default breeds via ga_breed_py; a custom fitness
#: is ``fn(seeds, close, volume, population_size, generations, seed)
#: -> list[str]``.
ga_fitness = Registry("ga_fitness")
if "engine" not in ga_fitness.names():
    ga_fitness.register(
        "engine",
        alpha_core.ga_breed_py,
        source="engine",
        description="engine GA, fixed fitness mean score x next-bar return;"
        " custom fitness = python fn(seeds, close, volume, population_size,"
        " generations, seed) -> list[str]; use quantcore.alpha.score() as the"
        " scoring primitive inside custom fitnesses",
    )


class EngineQuantitativeModel:
    """Thin model adapter over the Rust expression evaluator.

    ``dsl`` is explicit because the expression is part of model semantics;
    no expression is silently selected by a call site. Instances are both
    callable and provide ``score`` (the old adapter's dual surface), so they
    satisfy the plain callable contract of ``quantitative_models``.
    """

    def __init__(self, dsl: str) -> None:
        self.dsl = alpha_core.validate_expression_py(dsl)

    def score(self, close: Sequence[float], volume: Sequence[float]) -> list[float]:
        matrix = alpha_core.execute_batch_py([self.dsl], list(close), list(volume))
        return list(matrix[0])

    __call__ = score


quantitative_models = Registry("quantitative_models")
# This registered built-in names its expression explicitly. Other DSL
# expressions use ``EngineQuantitativeModel(dsl)`` so no model semantics are
# selected by an implicit default.
if "engine_close" not in quantitative_models.names():
    quantitative_models.register(
        "engine_close",
        EngineQuantitativeModel("close"),
        source="engine",
        description="Rust alpha expression evaluator; construct with explicit"
        " DSL for other expressions",
    )


def score_model(
    model: str | object,
    close: list[float],
    volume: list[float],
) -> list[float]:
    """Score one observation window through the quantitative-model contract.

    Parameters
    ----------
    model : str | object
        A registered ``quantitative_models`` name, or any object providing
        ``score(close, volume) -> list[float]``.
    close : list[float]
        Close prices, one per bar.
    volume : list[float]
        Volumes, one per bar.

    Returns
    -------
    list[float]
        One score per bar (z-units where the model produces them).

    Raises
    ------
    ValueError
        Empty/mismatched inputs, wrong output length, or no finite scores.
    TypeError
        ``model`` is neither a registered name nor a score-providing object.
    """
    if not close:
        raise ValueError("close and volume must be non-empty")
    if len(close) != len(volume):
        raise ValueError(
            f"close and volume lengths differ ({len(close)} != {len(volume)})"
        )
    if isinstance(model, str):
        implementation = quantitative_models.get(model).fn
        score_method = getattr(implementation, "score", None)
        if not callable(score_method):
            raise TypeError(
                f"registered quantitative model {model!r} does not provide"
                " callable score(close, volume)"
            )
    else:
        score_method = getattr(model, "score", None)
        if not callable(score_method):
            raise TypeError(
                "model must be a registered quantitative_models name or"
                " provide score(close, volume)"
            )
    scores = list(score_method(close, volume))
    if len(scores) != len(close):
        raise ValueError(
            f"quantitative model returned {len(scores)} scores for {len(close)} bars"
        )
    if not any(math.isfinite(value) for value in scores):
        raise ValueError("quantitative model returned no finite scores")
    return scores


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _alpha_id(dsl: str) -> str:
    """Deterministic alpha id from the canonical DSL (stable across runs)."""
    return "alpha-" + hashlib.sha256(dsl.encode("utf-8")).hexdigest()[:8]






def _daily(pnl: list[float], bars_per_day: int) -> list[float]:
    """Aggregate per-bar PnL into consecutive per-day sums."""
    return [sum(pnl[i : i + bars_per_day]) for i in range(0, len(pnl), bars_per_day)]


def _rank_ic(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman-rank correlation via double argsort (numpy only)."""
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    rx -= rx.mean()
    ry -= ry.mean()
    denom = math.sqrt(float((rx * rx).sum() * (ry * ry).sum()))
    if denom == 0.0:
        return 0.0
    return float((rx * ry).sum()) / denom


def _icir(score: list[float], returns: list[float], horizon: int, window: int) -> float | None:
    """ICIR = mean/std of per-block rank ICs (block length = ``window``).

    Returns None when fewer than two usable blocks exist (the gate treats
    the check as not-applicable).
    """
    n = len(score)
    max_t = n - horizon
    ics: list[float] = []
    start = 0
    while start < max_t:
        end = min(start + window, max_t)
        if end - start >= 8:
            x = np.asarray(score[start:end], dtype=float)
            y = np.asarray(returns[start + horizon : end + horizon], dtype=float)
            finite = np.isfinite(x) & np.isfinite(y)
            if int(finite.sum()) >= 8:
                ics.append(_rank_ic(x[finite], y[finite]))
        start = end
    if len(ics) < 2:
        return None
    mean = float(np.mean(ics))
    std = float(np.std(ics, ddof=1))
    if std == 0.0 or not math.isfinite(std):
        return None
    return mean / std


def _instrument_for(bars: BarFrame) -> Instrument:
    """Resolve the bar window's instrument (bare symbol from the id).

    ``bars.instrument_id`` is ``"<SYMBOL>.<VENUE>"`` (e.g. ``"VN30F1M.HNX"``);
    ``Instrument.load`` takes the bare symbol, so the venue suffix is
    stripped here.
    """
    symbol = bars.instrument_id.split(".", 1)[0]
    return Instrument.load(symbol)


def _window_provenance(bars: BarFrame) -> dict:
    """JSON-safe provenance dict for the evaluated bar window."""
    window = bars.window
    return {
        "instrument_id": window.instrument_id,
        "bar_type": window.bar_type,
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "n_bars": int(window.n_bars),
    }


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def validate_seed(dsl: str) -> str:
    """Return the canonical DSL form; raises ValueError on invalid syntax."""
    return alpha_core.validate_expression_py(dsl)


def score(expressions: list[str], close: list[float], volume: list[float]) -> list[list[float]]:
    """Batch-score expressions over close/volume.

    The scoring primitive for custom ``ga_fitness`` functions: one engine
    call, one row per expression.

    Parameters
    ----------
    expressions : list[str]
        DSL expressions (canonicalized first for safety).
    close : list[float]
        Close prices, one per bar.
    volume : list[float]
        Volumes, one per bar.

    Returns
    -------
    list[list[float]]
        One score series (z-units) per expression, in input order.
    """
    return alpha_core.execute_batch_py(list(expressions), list(close), list(volume))


def evaluate_seed(
    dsl: str,
    bars: BarFrame,
    config: AlphaConfig | None = None,
) -> TearSheet:
    """Single-alpha evaluation: canonical simulation + screening -> TearSheet.

    Pipeline: canonicalize -> batch score -> sanitize -> canonical position
    -> net/gross PnL -> metrics (Sharpe, max drawdown, cost drag, IC ladder,
    walk-forward, ICIR) -> gate verdict "IN"/"OUT" with failing reasons.
    Transaction costs use the bar instrument's cost model
    (``Instrument.cost.cost_per_side_frac``). With
    ``config.record_trial=True`` the evaluation is appended to the trial
    ledger.

    Parameters
    ----------
    dsl : str
        Seed expression in the canonical DSL.
    bars : BarFrame
        The bar window to evaluate over (close/volume feed the engine).
    config : AlphaConfig | None
        Defaults to ``AlphaConfig()``.

    Returns
    -------
    TearSheet
        Metrics, verdict, failing reasons and provenance (engine version,
        harness, gate, window).

    Raises
    ------
    ValueError
        Invalid DSL syntax, or the expression produces no finite values.

    Notes
    -----
    Units: scores and composites are z-units; PnL metrics are in canonical
    composite units (position x return per bar); ``cost_drag_pct`` is a
    percent value.
    """
    cfg = config or AlphaConfig()
    gate = cfg.gate
    h = cfg.harness
    dsl_canonical = validate_seed(dsl)

    close = bars.close_list()
    volume = bars.volume_list()
    bpd = h.bars_per_day
    instrument = _instrument_for(bars)
    cost_per_side = instrument.cost.cost_per_side_frac

    matrix = alpha_core.execute_batch_py([dsl_canonical], close, volume)
    if not any(math.isfinite(v) for v in matrix[0]):
        raise ValueError(
            f"expression {dsl_canonical!r} produces no finite values: it"
            " references fields absent from the data (only close/volume are"
            " available in the research catalog)"
        )
    sane = sanitize_scores(matrix[0])
    position = alpha_core.canonical_map_py(
        sane,
        span=h.span,
        z_window=h.z_window,
        band=h.band,
        cap=h.cap,
        bars_per_day=bpd,
    ).position
    returns = close_returns(close)
    net = alpha_core.compute_pnl_py(position, returns, cost_per_side, bpd).net
    gross = alpha_core.compute_pnl_py(position, returns, 0.0, bpd).net

    daily_net = _daily(net, bpd)
    daily_gross = _daily(gross, bpd)
    net_sum = sum(daily_net)
    gross_sum = sum(daily_gross)
    # Engine convention: drag = cost / |gross|, always non-negative; the
    # naive 1 - net/gross goes negative when gross < 0 and silently passes
    # the gate.
    cost_drag_pct = (
        100.0 * (gross_sum - net_sum) / abs(gross_sum) if gross_sum != 0.0 else math.inf
    )

    net_sharpe = alpha_core.sharpe_py(daily_net, bars_per_day=bpd)
    max_drawdown = alpha_core.max_drawdown_py(daily_net)
    ladder = [
        {"horizon": r.horizon, "mean_ic": r.mean_ic, "t_stat": r.t_stat}
        for r in alpha_core.ic_ladder_py(
            sane, returns, list(gate.ic_horizons), gate.ic_window, bpd
        )
    ]
    best = max(ladder, key=lambda r: abs(r["mean_ic"]), default={"horizon": 1, "mean_ic": 0.0})
    best_abs_ic = abs(float(best["mean_ic"]))
    icir = _icir(sane, returns, int(best["horizon"]), gate.ic_window)

    wf = alpha_core.walk_forward_py(daily_net, gate.walk_forward_block_days, gate.ann_factor)
    wf_blocks = len(wf.blocks)

    metrics = {
        "net_sharpe": net_sharpe,
        "max_drawdown": max_drawdown,
        "cost_drag_pct": cost_drag_pct,
        "total_net_pnl": net_sum,
        "ic_ladder": ladder,
        "best_horizon": int(best["horizon"]),
        "best_abs_ic": best_abs_ic,
        "icir": icir,
        "walk_forward": {
            "positive_pct": wf.positive_pct,
            "worst_block_sharpe": wf.worst_block_sharpe,
            "n_blocks": wf_blocks,
        },
        "hints": [],
    }
    if icir is not None and icir < gate.min_icir and best_abs_ic > gate.min_abs_ic:
        metrics["hints"].append(
            "icir is signed: a strong INVERSE signal fails it. "
            "Try negating the expression (e.g. '-(' + dsl_canonical + ')')."
        )
    if wf_blocks < 2:
        metrics["hints"].append(
            f"walk-forward had only {wf_blocks} block(s); stability check not applicable"
            " (increase the sample or lower walk_forward_block_days)."
        )

    checks = [
        ("ic", best_abs_ic > gate.min_abs_ic),
        ("cost_drag", cost_drag_pct < gate.max_cost_drag_pct),
        ("net_sharpe", math.isfinite(net_sharpe) and net_sharpe > gate.min_net_sharpe),
        (
            "walk_forward",
            wf_blocks < 2 or wf.positive_pct > gate.min_positive_blocks_pct,
        ),
        ("icir", icir is None or icir > gate.min_icir),
    ]
    if cfg.n_trials > 0:
        # The bar rises with the effective trial count (deflated-Sharpe
        # logic); the trial count is the caller's responsibility
        # (screen_batch accounting).
        deflated = alpha_core.deflated_threshold_py(cfg.n_trials, gate.sharpe_variance)
        checks.append(
            ("deflated_sharpe", math.isfinite(net_sharpe) and net_sharpe > deflated)
        )
    reasons = tuple(name for name, ok in checks if not ok)
    verdict = "IN" if not reasons else "OUT"

    provenance = {
        "engine_version": getattr(alpha_core, "__version__", "unknown"),
        "harness": asdict(h),
        "gate": asdict(gate),
        "window": _window_provenance(bars),
    }
    tear = TearSheet(
        alpha_id=_alpha_id(dsl_canonical),
        dsl=dsl_canonical,
        metrics=metrics,
        verdict=verdict,
        reasons=reasons,
        provenance=provenance,
    )

    if cfg.record_trial:
        append_trial_ledger(
            {
                "alpha_id": tear.alpha_id,
                "dsl": tear.dsl,
                "date": date.today().isoformat(),
                "verdict": tear.verdict,
                "reasons": list(tear.reasons),
                "metrics_summary": {
                    "net_sharpe": metrics["net_sharpe"],
                    "best_abs_ic": best_abs_ic,
                    "cost_drag_pct": cost_drag_pct,
                },
                "provenance": provenance,
            }
        )
    return tear


def screen_batch(
    seeds: list[str],
    bars: BarFrame,
    config: AlphaConfig | None = None,
) -> ScreenResult:
    """Evaluate a batch and report the screening funnel.

    Every candidate is recorded in the trial ledger when
    ``config.record_trial`` is True (the funnel is where trials are
    counted). ``survivor_count`` counts FULL-gate survivors (verdict IN),
    while ``ic_pass_count``/``drag_pass_count`` are the forecast- and
    cost-gate counts from the engine screening.

    Parameters
    ----------
    seeds : list[str]
        Candidate DSL expressions (seeds or GA-bred).
    bars : BarFrame
        The bar window; loaded once and shared by the whole batch.
    config : AlphaConfig | None
        Defaults to ``AlphaConfig()``.

    Returns
    -------
    ScreenResult
        Funnel counts, one TearSheet per candidate, survivor DSL strings.

    Raises
    ------
    ValueError
        Empty seed list.
    """
    if not seeds:
        raise ValueError("seeds must be non-empty")
    cfg = config or AlphaConfig()
    tears = [evaluate_seed(e, bars, cfg) for e in seeds]
    funnel = alpha_core.screen_candidates_py(
        [t.metrics["best_abs_ic"] for t in tears],
        [t.metrics["cost_drag_pct"] for t in tears],
        cfg.gate.min_abs_ic,
        cfg.gate.max_cost_drag_pct,
    )
    survivors = [t.dsl for t in tears if t.verdict == "IN"]
    return ScreenResult(
        funnel={
            "total_candidates": funnel.total_candidates,
            "ic_pass_count": funnel.ic_pass_count,
            "drag_pass_count": funnel.drag_pass_count,
            "survivor_count": len(survivors),
        },
        tear_sheets=tears,
        survivors=survivors,
    )


def mine_seeds(
    seeds: list[str],
    bars: BarFrame,
    config: AlphaConfig | None = None,
) -> list[str]:
    """Breed the GA from evaluation-passing seeds (WorldQuant-style).

    Every seed is canonicalized first (invalid seeds raise ValueError naming
    the offending expression). Uses the ``ga_fitness`` registry "engine"
    method with ``config.ga_population_size`` / ``config.ga_generations`` /
    ``config.ga_seed``.

    Parameters
    ----------
    seeds : list[str]
        Evaluation-passing seed expressions.
    bars : BarFrame
        The bar window feeding the fitness evaluation.
    config : AlphaConfig | None
        Defaults to ``AlphaConfig()``.

    Returns
    -------
    list[str]
        The final population's canonical DSL strings ranked best-first,
        deduplicated; deterministic for a fixed ``ga_seed``.

    Raises
    ------
    ValueError
        Empty seed list, invalid seed syntax, or a fitness that returns
        non-string entries.

    Notes
    -----
    Extension slot: the ``ga_fitness`` registry "engine" default delegates
    to the Rust GA binding (fixed fitness = mean score x next-bar return);
    a custom fitness is a Python function with the same signature
    ``fn(seeds, close, volume, population_size, generations, seed) ->
    list[str]`` using :func:`score` as the scoring primitive.
    """
    if not seeds:
        raise ValueError("seeds must be non-empty")
    cfg = config or AlphaConfig()
    canonical = [validate_seed(s) for s in seeds]
    close = bars.close_list()
    volume = bars.volume_list()
    result = ga_fitness.call(
        "engine",
        canonical,
        close,
        volume,
        cfg.ga_population_size,
        cfg.ga_generations,
        cfg.ga_seed,
    )
    # Custom fitnesses are not trusted: validate + canonicalize every element
    # (the engine path is idempotent here) and dedupe so trial accounting and
    # deflated-threshold priors are not inflated by duplicates.
    validated: list[str] = []
    for i, dsl in enumerate(result):
        if not isinstance(dsl, str):
            raise ValueError(
                f"ga_fitness 'engine' returned non-string at index {i}: {dsl!r}"
            )
        validated.append(validate_seed(dsl))
    seen: set[str] = set()
    out: list[str] = []
    for dsl in validated:
        if dsl not in seen:
            seen.add(dsl)
            out.append(dsl)
    return out


def build_spec_sheet(sheet: TearSheet, bars: BarFrame) -> SpecSheet:
    """Build the PASS artifact: expectations consumed by the Portfolio
    Researcher, the divergence gauges and the live kill criteria.

    Holding period = ladder horizon with max |mean IC|; expected ICs are the
    full ladder (horizon -> mean IC); capacity = 5% of mean daily volume
    (documented participation heuristic); kill criteria = rolling 20-day IC
    below zero for ten consecutive days (the documented example).

    Parameters
    ----------
    sheet : TearSheet
        The evaluation tear sheet (must carry ``ic_ladder`` metrics).
    bars : BarFrame
        The same bar window the tear sheet was evaluated on (volume feeds
        the capacity estimate).

    Returns
    -------
    SpecSheet
        Expectations incl. ``expected_ic`` and the default
        ``cost_model_bps``.
    """
    ladder = sheet.metrics.get("ic_ladder") or []
    best = max(ladder, key=lambda r: abs(r["mean_ic"]), default=None)
    holding = int(best["horizon"]) if best else 1
    expected_sharpe = float(sheet.metrics.get("net_sharpe", 0.0))
    expected_ic = {str(r["horizon"]): float(r["mean_ic"]) for r in ladder}

    ts = bars.ts
    volume = np.asarray(bars.volume, dtype=float)
    daily_volume = pd.Series(volume, index=ts).groupby(ts.date).sum()
    mean_daily_volume = float(daily_volume.mean()) if len(daily_volume) else 0.0
    capacity = int(math.floor(mean_daily_volume * 0.05)) if mean_daily_volume > 0 else 0

    return SpecSheet(
        alpha_id=sheet.alpha_id,
        expected_holding_period_bars=holding,
        expected_net_sharpe=expected_sharpe,
        capacity_contracts=capacity,
        regime_notes="",
        kill_criteria={"rolling_ic_window_days": 20, "below": 0.0, "consecutive_days": 10},
        expected_ic=expected_ic,
    )


def deliver(
    pool: AlphaPool,
    sheet: TearSheet,
    spec: SpecSheet,
    *,
    alpha_id: str | None = None,
    author: str = "research",
    tags: tuple[str, ...] = (),
    family: str | None = None,
    source: str = "seed",
) -> PoolEntry:
    """Deliver an IN-verdict alpha into the in-memory pool (handoff artifact).

    Builds the PoolEntry (schema_version "2", embedding the tear sheet and
    the spec sheet) and adds it to ``pool``. SAVING is the caller's explicit
    ``pool.save()``.

    Parameters
    ----------
    pool : AlphaPool
        The pool to append to.
    sheet : TearSheet
        The evaluation tear sheet; verdict must be "IN".
    spec : SpecSheet
        The expectation sheet (see :func:`build_spec_sheet`).
    alpha_id : str | None
        Override id; defaults to the deterministic id of the canonical DSL.
    author : str
        Author tag recorded in the entry.
    tags : tuple[str, ...]
        Free-form tags.
    family : str | None
        Mining family label (GA lineage).
    source : str
        Provenance of the alpha ("seed" or "ga").

    Returns
    -------
    PoolEntry
        The entry that was added to ``pool``.

    Raises
    ------
    ValueError
        The tear sheet verdict is not "IN".
    """
    if sheet.verdict != "IN":
        raise ValueError(
            f"cannot deliver alpha {sheet.alpha_id!r} with verdict"
            f" {sheet.verdict!r}; reasons: {sheet.reasons}"
        )
    entry = PoolEntry(
        alpha_id=alpha_id or _alpha_id(sheet.dsl),
        dsl=sheet.dsl,
        author=author,
        tags=tuple(tags),
        family=family,
        source=source,
        tear_sheet=sheet,
        spec_sheet=spec,
    )
    pool.add(entry)
    return entry
