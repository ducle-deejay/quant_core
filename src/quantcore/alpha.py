"""quantcore.alpha - Quantitative Researcher module (decision note DEC-017).

WorldQuant-style workflow: hand-written seed -> single-alpha evaluation
(Component 1 - Canonical Simulation + Component 2 - Evaluation and
Screening) -> only passing seeds enter GA mining -> bred candidates are
evaluated -> passing candidates are delivered to the pool folder consumed
by the Portfolio Researcher.

Extension slot: ``ga_fitness`` registry - default "engine" delegates to the
Rust GA binding (fixed fitness = mean score x next-bar return); a custom
fitness is a Python function with the same signature
``fn(seeds, close, volume, population_size, generations, seed) -> list[str]``
(phase-2 evaluation harness, DEC-017).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date

import alpha_core
import numpy as np

from quantcore.core.artifacts import append_trial_ledger
from quantcore.core.config import DataConfig
from quantcore.core.data import close_volume, load_bars
from quantcore.core.pool import PoolEntry, load_pool, write_pool_entry, write_pool_index
from quantcore.core.registry import Registry
from quantcore.core.extensions import QuantitativeModel, _CallableQuantitativeModel
from quantcore.core.report import SpecSheet, TearSheet

try:  # trading.contracts is the live wiring contract source (DEC-017)
    from trading.contracts import HarnessParams
except ImportError:  # pragma: no cover - fallback mirror for standalone use
    from dataclasses import dataclass as _dc

    @_dc(frozen=True)
    class HarnessParams:  # type: ignore[no-redef]
        span: int = 8
        z_window: int = 480
        band: float = 0.35
        cap: float = 2.0
        cost_per_side: float = 0.000229
        bars_per_day: int = 240


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GateCriteria:
    """Component 2 - Evaluation and Screening gate thresholds.

    Phase-1 gate: absolute Information Coefficient, cost drag, net Sharpe,
    walk-forward stability, ICIR. The deflated-threshold wiring (canon
    section 3.4) is part of the phase-2 evaluation harness and is recorded
    in DEC-017.
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
    """Everything one research call needs; every field has a default."""

    harness: HarnessParams = field(default_factory=HarnessParams)
    gate: GateCriteria = field(default_factory=GateCriteria)
    data: DataConfig | None = None
    ga_population_size: int = 100
    ga_generations: int = 20
    ga_seed: int = 42
    n_trials: int = 0  # effective trial count; >0 wires the deflated-Sharpe check


# --------------------------------------------------------------------------- #
# Extension registry
# --------------------------------------------------------------------------- #

#: GA fitness slot (DEC-017): engine default breeds via ga_breed_py.
ga_fitness = Registry("ga_fitness")
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
    no expression is silently selected by a call site.
    """

    def __init__(self, dsl: str) -> None:
        self.dsl = alpha_core.validate_expression_py(dsl)

    def score(self, close: Sequence[float], volume: Sequence[float]) -> list[float]:
        matrix = alpha_core.execute_batch_py([self.dsl], list(close), list(volume))
        return list(matrix[0])


quantitative_models = Registry(
    "quantitative_models",
    contract=QuantitativeModel,
    capability="score",
    adapter=_CallableQuantitativeModel,
)
# This registered built-in names its expression explicitly. Other DSL
# expressions use ``EngineQuantitativeModel(dsl)`` so no model semantics are
# selected by an implicit default.
quantitative_models.register(
    "engine_close",
    EngineQuantitativeModel("close"),
    source="engine",
    description="Rust alpha expression evaluator; construct with explicit DSL for other expressions",
)


def score_model(
    model: str | QuantitativeModel,
    close: list[float],
    volume: list[float],
) -> list[float]:
    """Score one observation window through the quantitative-model contract."""
    if not close:
        raise ValueError("close and volume must be non-empty")
    if len(close) != len(volume):
        raise ValueError(
            f"close and volume lengths differ ({len(close)} != {len(volume)})"
        )
    if isinstance(model, str):
        scores = list(quantitative_models.call(model, close, volume))
    else:
        if not isinstance(model, QuantitativeModel):
            raise TypeError("model must be a registered name or implement QuantitativeModel.score")
        scores = list(model.score(close, volume))
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


def _sanitize_scores(series: list[float]) -> list[float]:
    """Forward-fill non-finite scores (mirror of trading.portfolio).

    Leading non-finite values take the first finite value; interior ones
    carry the last finite value forward; an all-non-finite series maps to
    zeros (engine ``sanitize_scores`` semantics, observation OBS-011).
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


def _close_returns(close: list[float]) -> list[float]:
    r = [0.0] * len(close)
    for t in range(1, len(close)):
        r[t] = close[t] / close[t - 1] - 1.0
    return r


def _daily(pnl: list[float], bars_per_day: int) -> list[float]:
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

    Returns None when fewer than two usable blocks exist (check treated as
    not-applicable by the gate).
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


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def validate_seed(dsl: str) -> str:
    """Return the canonical DSL form; raises ValueError on invalid syntax."""
    return alpha_core.validate_expression_py(dsl)


def _resolve_data(config: AlphaConfig | None, data: DataConfig | None) -> DataConfig:
    if data is not None:
        return data
    if config is not None and config.data is not None:
        return config.data
    return DataConfig()


def evaluate_seed(
    dsl: str,
    config: AlphaConfig | None = None,
    data: DataConfig | None = None,
    record_trial: bool = False,
    trial_root=None,
    source: str = "seed",
    bars_df=None,
) -> TearSheet:
    """Single-alpha evaluation: Component 1 + Component 2 -> TearSheet.

    Pipeline: canonicalize -> batch score -> sanitize -> canonical position
    -> net/gross PnL -> metrics (Sharpe, max drawdown, cost drag, IC ladder,
    walk-forward, ICIR) -> gate verdict "IN"/"OUT" with failing reasons.
    With ``record_trial=True`` the evaluation is appended to the trial
    ledger (mandatory trial accounting, canon Component 2 section 3.4).
    """
    cfg = config or AlphaConfig()
    gate = cfg.gate
    h = cfg.harness
    eff_data = _resolve_data(cfg, data)
    dsl_canonical = validate_seed(dsl)

    df = bars_df if bars_df is not None else load_bars(eff_data)
    close, volume = close_volume(df)
    bpd = h.bars_per_day

    matrix = alpha_core.execute_batch_py([dsl_canonical], close, volume)
    if not any(math.isfinite(v) for v in matrix[0]):
        raise ValueError(
            f"expression {dsl_canonical!r} produces no finite values: it"
            " references fields absent from the data (only close/volume are"
            " available in the research catalog)"
        )
    sane = _sanitize_scores(matrix[0])
    position = alpha_core.canonical_map_py(
        sane,
        span=h.span,
        z_window=h.z_window,
        band=h.band,
        cap=h.cap,
        bars_per_day=bpd,
    ).position
    returns = _close_returns(close)
    net = alpha_core.compute_pnl_py(position, returns, h.cost_per_side, bpd).net
    gross = alpha_core.compute_pnl_py(position, returns, 0.0, bpd).net

    daily_net = _daily(net, bpd)
    daily_gross = _daily(gross, bpd)
    net_sum = sum(daily_net)
    gross_sum = sum(daily_gross)
    # Engine convention (canonical pnl.rs): drag = cost / |gross|, always
    # non-negative; the naive 1 - net/gross goes negative when gross < 0 and
    # silently passes the gate (practitioner-review finding).
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
        # Canon Component 2 section 3.4: the bar rises with the effective
        # trial count (deflated-Sharpe logic). Wired in the API now that the
        # ledger exists (practitioner-review finding); trial count is the
        # caller's responsibility (screen_batch accounting).
        deflated = alpha_core.deflated_threshold_py(cfg.n_trials, gate.sharpe_variance)
        checks.append(
            ("deflated_sharpe", math.isfinite(net_sharpe) and net_sharpe > deflated)
        )
    reasons = tuple(name for name, ok in checks if not ok)
    verdict = "IN" if not reasons else "OUT"

    provenance = {
        "engine_version": getattr(alpha_core, "__version__", "unknown"),
        "source": source,
        "harness": asdict(h),
        "gate": asdict(gate),
        "data": asdict(eff_data),
    }
    tear = TearSheet(
        alpha_id=_alpha_id(dsl_canonical),
        dsl=dsl_canonical,
        metrics=metrics,
        verdict=verdict,
        reasons=reasons,
        provenance=provenance,
    )

    if record_trial:
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
            },
            root=trial_root,
        )
    return tear


def evaluate_candidate(
    dsl: str,
    config: AlphaConfig | None = None,
    data: DataConfig | None = None,
    record_trial: bool = False,
    trial_root=None,
) -> TearSheet:
    """Evaluate a GA-bred candidate (source="ga"); same pipeline as a seed."""
    return evaluate_seed(
        dsl,
        config=config,
        data=data,
        record_trial=record_trial,
        trial_root=trial_root,
        source="ga",
    )


def score(expressions: list[str], close: list[float], volume: list[float]) -> list[list[float]]:
    """Batch-score expressions over close/volume — the scoring primitive for
    custom ``ga_fitness`` functions (DEC-017; UAT finding: the extension
    contract previously forced writers to import raw ``alpha_core``)."""
    return alpha_core.execute_batch_py(list(expressions), list(close), list(volume))


def mine_seeds(
    seeds: list[str],
    config: AlphaConfig | None = None,
    data: DataConfig | None = None,
    fitness: str = "engine",
    population_size: int | None = None,
    generations: int | None = None,
    seed: int | None = None,
) -> list[str]:
    """Breed the GA from evaluation-passing seeds (WorldQuant-style).

    Every seed is canonicalized first (invalid seeds raise ValueError
    naming the offending expression). Returns the final population's DSL
    strings ranked best-first; deterministic for a fixed ``seed``.
    """
    if not seeds:
        raise ValueError("seeds must be non-empty")
    cfg = config or AlphaConfig()
    eff_data = _resolve_data(cfg, data)
    canonical = [validate_seed(s) for s in seeds]
    df = load_bars(eff_data)
    close, volume = close_volume(df)
    result = ga_fitness.call(
        fitness,
        canonical,
        close,
        volume,
        population_size or cfg.ga_population_size,
        generations or cfg.ga_generations,
        seed if seed is not None else cfg.ga_seed,
    )
    # Custom fitnesses are not trusted: validate + canonicalize every element
    # (the engine path is idempotent here) and dedupe so trial accounting and
    # deflated-threshold priors are not inflated by duplicates (UAT findings).
    validated: list[str] = []
    for i, dsl in enumerate(result):
        if not isinstance(dsl, str):
            raise ValueError(
                f"fitness {fitness!r} returned non-string at index {i}: {dsl!r}"
            )
        validated.append(validate_seed(dsl))
    seen: set[str] = set()
    out: list[str] = []
    for dsl in validated:
        if dsl not in seen:
            seen.add(dsl)
            out.append(dsl)
    return out


def screen_batch(
    expressions: list[str],
    config: AlphaConfig | None = None,
    data: DataConfig | None = None,
    record_trials: bool = True,
    trial_root=None,
    source: str = "seed",
) -> dict:
    """Evaluate a batch and report the screening funnel (canon 3.1-3.5).

    Every candidate is recorded in the trial ledger when
    ``record_trials=True`` (the funnel is where trials are counted).
    ``source`` tags provenance ("seed" or "ga") for GA-bred batches so the
    trial ledger is not misattributed (UAT finding).
    Returns {"funnel": {...counts}, "tear_sheets": [...], "survivors": [...]}
    where ``survivor_count`` counts FULL-gate survivors (verdict IN), while
    ``ic_pass_count``/``drag_pass_count`` are the forecast- and cost-gate
    counts from the engine screening.
    """
    if not expressions:
        raise ValueError("expressions must be non-empty")
    cfg = config or AlphaConfig()
    eff_data = _resolve_data(cfg, data)
    df = load_bars(eff_data)  # loaded ONCE for the whole batch (perf finding)
    tears = [
        evaluate_seed(
            e,
            config=cfg,
            data=data,
            record_trial=record_trials,
            trial_root=trial_root,
            source=source,
            bars_df=df,
        )
        for e in expressions
    ]
    funnel = alpha_core.screen_candidates_py(
        [t.metrics["best_abs_ic"] for t in tears],
        [t.metrics["cost_drag_pct"] for t in tears],
        cfg.gate.min_abs_ic,
        cfg.gate.max_cost_drag_pct,
    )
    survivors = [t.dsl for t in tears if t.verdict == "IN"]
    return {
        "funnel": {
            "total_candidates": funnel.total_candidates,
            "ic_pass_count": funnel.ic_pass_count,
            "drag_pass_count": funnel.drag_pass_count,
            "survivor_count": len(survivors),
        },
        "tear_sheets": tears,
        "survivors": survivors,
    }


def build_spec_sheet(
    tear_sheet: TearSheet,
    data: DataConfig | None = None,
    config: AlphaConfig | None = None,
) -> SpecSheet:
    """Component 2 PASS artifact (canon section 3.5): expectations consumed by
    the Portfolio Researcher, the divergence gauges and live kill criteria.

    holding period = ladder horizon with max |mean IC|; capacity = 5% of
    mean daily volume (documented participation heuristic); kill criteria =
    rolling 20-day IC below zero for two weeks (canon example).
    """
    ladder = tear_sheet.metrics.get("ic_ladder") or []
    best = max(ladder, key=lambda r: abs(r["mean_ic"]), default=None)
    holding = int(best["horizon"]) if best else 1
    expected_sharpe = float(tear_sheet.metrics.get("net_sharpe", 0.0))

    cfg = config or AlphaConfig()
    eff_data = _resolve_data(cfg, data)
    df = load_bars(eff_data)
    mean_daily_volume = float(df.groupby(df["ts"].dt.date)["volume"].sum().mean())
    capacity = int(math.floor(mean_daily_volume * 0.05)) if mean_daily_volume > 0 else 0

    return SpecSheet(
        alpha_id=tear_sheet.alpha_id,
        expected_holding_period_bars=holding,
        expected_net_sharpe=expected_sharpe,
        capacity_contracts=capacity,
        regime_notes="",
        kill_criteria={"rolling_ic_window_days": 20, "below": 0.0, "consecutive_days": 10},
    )


def deliver_to_pool(
    tear_sheet: TearSheet,
    spec_sheet: SpecSheet,
    *,
    alpha_id: str | None = None,
    author: str = "research",
    tags=(),
    family: str | None = None,
    source: str | None = None,
    pool_root=None,
) -> PoolEntry:
    """Deliver an IN-verdict alpha into the pool folder (handoff artifact).

    Writes ``<pool_root>/alphas/<alpha_id>.json`` and regenerates
    ``index.json`` from the whole folder. Raises ValueError for OUT.
    """
    if tear_sheet.verdict != "IN":
        raise ValueError(
            f"cannot deliver alpha {tear_sheet.alpha_id!r} with verdict"
            f" {tear_sheet.verdict!r}; reasons: {tear_sheet.reasons}"
        )
    entry = PoolEntry(
        alpha_id=alpha_id or _alpha_id(tear_sheet.dsl),
        dsl=tear_sheet.dsl,
        author=author,
        tags=tuple(tags),
        family=family,
        source=source or "seed",
        spec_sheet=spec_sheet.to_dict(),
    )
    write_pool_entry(entry, root=pool_root)
    write_pool_index(load_pool(pool_root), root=pool_root)
    return entry
