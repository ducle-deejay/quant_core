"""Portfolio orchestration for the live runner.
One bar buffer in, one signed target out; pure ``alpha_core`` + stdlib, no Nautilus.
"""

from __future__ import annotations

import math
from datetime import datetime

import alpha_core

from core import AccountLimits
from core.signal import rolling_vol, sanitize_scores
from core import Instrument
from core import Portfolio
from core import PortfolioConfig
from core import TargetPosition
from core.artifacts import AlphaPool, WeightsArtifact
from core.mapping import max_contracts_at
from core.mapping import to_contracts

#: Trailing-window length (bars) for the realised-vol estimate.
VOL_WINDOW = 20

#: Extra bars beyond ``z_window`` required before the buffer is considered
#: warmed up (the rolling z-score needs a full window plus signal room).
WARMUP_MARGIN = 320

#: Milestone-1 seed alpha set: 6 hand-written DSL expressions over
#: ``close``/``volume``, each verified with ``alpha_core.validate_expression_py``.
SEED_EXPRESSIONS: tuple[str, ...] = (
    "close - ewma(close, 8)",                        # short-term deviation vs 8-bar EWMA
    "ts_returns(close, 8)",                          # 8-bar momentum
    "-ts_returns(close, 5)",                         # 5-bar short-term reversal
    "ts_trend_slope(close, 20)",                     # 20-bar OLS trend slope
    "ts_returns(close, 8) * ts_zscore(volume, 20)",  # volume-confirmed momentum
    "close / ts_max(close, 20) - 1",                 # distance below/above 20-bar high
)


def _flat(ts: datetime, reason: str, components: dict[str, float] | None = None) -> TargetPosition:
    """Deterministic flat target (zero contracts, zero z) for a given reason."""
    return TargetPosition(
        ts=ts,
        target_contracts=0,
        z_target=0.0,
        reason=reason,
        components=components or {},
    )


class PortfolioOrchestrator(Portfolio):
    """Implements the ``Portfolio`` protocol: bars in, one target out.

    Pure ``alpha_core`` calls plus stdlib math; every step is deterministic.
    The configuration (expressions, weights, harness and limits) is validated
    once at construction so per-bar evaluation cannot fail on configuration
    errors. The contract ``instrument`` is fixed at construction and feeds
    the margin conversion (multiplier) in step 8.
    """

    def __init__(self, config: PortfolioConfig, instrument: Instrument) -> None:
        self.config = config
        self.instrument = instrument
        self._weights = self._validate_config(config)
        self._min_bars = config.harness.z_window + WARMUP_MARGIN

    @staticmethod
    def _validate_config(config: PortfolioConfig) -> tuple[float, ...]:
        if not config.expressions:
            raise ValueError("PortfolioConfig.expressions must be non-empty")
        if len(config.expressions) != len(config.weights):
            raise ValueError(
                "PortfolioConfig.expressions and weights must have equal length "
                f"(got {len(config.expressions)} and {len(config.weights)})"
            )
        for expr in config.expressions:
            if not isinstance(expr, str) or not expr.strip():
                raise ValueError(f"expressions must be non-empty strings (got {expr!r})")
            try:
                alpha_core.validate_expression_py(expr)
            except ValueError as exc:
                raise ValueError(f"invalid alpha expression {expr!r}: {exc}") from exc

        wsum = 0.0
        for w in config.weights:
            if not math.isfinite(w):
                raise ValueError(f"weights must be finite (got {w!r})")
            wsum += w
        if wsum <= 0.0:
            raise ValueError("weights must sum to a positive value")
        weights = tuple(w / wsum for w in config.weights)

        h = config.harness
        if h.span <= 0 or h.z_window <= 0 or h.bars_per_day <= 0:
            raise ValueError("harness span, z_window and bars_per_day must be positive")
        if h.band < 0.0:
            raise ValueError("harness band must be non-negative")
        if h.cap <= 0.0:
            raise ValueError("harness cap must be positive (contract conversion divides by cap)")
        if not math.isfinite(config.vol_target) or config.vol_target <= 0.0:
            raise ValueError("vol_target must be a positive finite fraction")
        if config.vol_floor is not None and (
            not math.isfinite(config.vol_floor) or config.vol_floor <= 0.0
        ):
            raise ValueError("vol_floor must be None or a positive finite fraction")
        limits = config.limits
        if limits.capital_vnd <= 0.0 or limits.margin_rate <= 0.0:
            raise ValueError("limits.capital_vnd and limits.margin_rate must be positive")
        if limits.safety_factor < 0.0:
            raise ValueError("limits.safety_factor must be non-negative")
        if limits.max_contracts < 0:
            raise ValueError("limits.max_contracts must be non-negative")
        return weights

    def compute_target(
        self,
        bars: dict[str, list[float]],
        ts: datetime,
    ) -> TargetPosition:
        """One bar buffer in, one signed ``TargetPosition`` out.

        Deterministic per-bar pipeline:

        1. Shape guards: ``bars`` must carry ``"close"`` and ``"volume"``
           lists of equal length; a buffer shorter than ``z_window +
           WARMUP_MARGIN`` yields a flat target with reason ``"warmup"``;
           missing/incompatible keys are invalid input.
        2. Value guards: any non-finite close/volume value, or any
           non-positive close (zero/negative price makes returns and the
           margin conversion meaningless), yields a flat ``"invalid-input"``
           target.
        3. Scoring: every configured expression is evaluated over the FULL
           buffers in ONE ``execute_batch_py`` call (never one call per
           alpha) -> one score row per expression.
        4. NaN sanitisation: ``execute_batch_py`` emits NaN during rolling
           warmup and the ``canonical_map_py`` binding rejects non-finite
           scores, so this module mirrors the Rust ``canonical_map``
           ``sanitize_scores`` semantics (forward-fill; all-non-finite maps
           to zeros) before calling the binding.
        5. Canonical mapping: ``canonical_map_py(score, span, z_window,
           band, cap, bars_per_day)`` from ``config.harness`` -> per-alpha
           position series in z units; the last element is recorded in
           ``components`` under its expression key (telemetry).
        6. Composite z: ``composite_score_py`` over the per-alpha position
           series with weights normalised to sum to 1 (research/live
           parity); the last element is the current composite z.
        7. Volatility targeting: rolling realised vol of simple close
           returns (sample std ddof=1 over a trailing ``VOL_WINDOW`` bar
           window, annualised by ``sqrt(bars_per_day)``; fewer than two
           samples or zero variance -> 0.0, the engine's ``ts_std``
           convention) into ``vol_target_py(composite, vol_est,
           config.vol_target, config.vol_floor)``; both annualised, so the
           target/estimate ratio is scale-invariant. The last element is
           the current target z.
        8. Contract conversion via ``core.mapping.to_contracts`` (the
           single score->contracts implementation shared with research):
           ``L_max = floor(limits.capital_vnd * limits.safety_factor /
           (limits.margin_rate * price * multiplier))``,
           ``raw = z / cap * L_max``, ``round(raw)`` half-to-even, clipped
           to ``+/-max_contracts``, with ``price`` = last close and
           ``cap`` = ``harness.cap``. No hysteresis on the live path
           (stateless conversion; research loops apply the band
           explicitly). ``z_target`` carries the pre-rounding z.
        9. Reason: ``"warmup"`` (buffer not yet long enough),
           ``"invalid-input"`` (malformed/non-finite/non-positive bars or
           an engine failure), then ``"cap-limited"`` when the un-clipped
           rounded contract count exceeds ``max_contracts``,
           ``"flat-no-signal"`` when it rounds to zero or the z is
           degenerate, else ``"signal"``.
        """
        cfg = self.config
        h = cfg.harness

        # 1-2. Shape and value guards (deterministic flat targets).
        if bars is None:
            return _flat(ts, "invalid-input")
        close = bars.get("close")
        volume = bars.get("volume")
        if close is None or volume is None:
            return _flat(ts, "invalid-input")
        if not isinstance(close, (list, tuple)) or not isinstance(volume, (list, tuple)):
            return _flat(ts, "invalid-input")
        if len(close) == 0 or len(close) != len(volume) or len(close) < self._min_bars:
            return _flat(ts, "warmup")
        if not all(math.isfinite(v) for v in close) or not all(math.isfinite(v) for v in volume):
            return _flat(ts, "invalid-input")
        if any(v <= 0.0 for v in close):
            return _flat(ts, "invalid-input")

        # 3. Score every expression in one engine call.
        try:
            matrix = alpha_core.execute_batch_py(
                list(cfg.expressions), list(close), list(volume)
            )
        except ValueError:
            # Defensive: precluded by init-time validation and the guards
            # above; degrade to flat rather than crash the live loop.
            return _flat(ts, "invalid-input")

        # 4-5. Sanitise warmup NaN and map each row to canonical positions.
        positions: list[list[float]] = []
        components: dict[str, float] = {}
        for expr, row in zip(cfg.expressions, matrix):
            sane = sanitize_scores(row)
            res = alpha_core.canonical_map_py(
                sane,
                span=h.span,
                z_window=h.z_window,
                band=h.band,
                cap=h.cap,
                bars_per_day=h.bars_per_day,
            )
            positions.append(res.position)
            components[expr] = res.position[-1]

        # 6-7. Composite z, then vol targeting (engine functions reused).
        composite = alpha_core.composite_score_py(positions, list(self._weights))
        vol_est = rolling_vol(list(close), VOL_WINDOW, h.bars_per_day)
        vol_series = alpha_core.vol_target_py(
            composite, vol_est, cfg.vol_target, cfg.vol_floor
        )
        z = vol_series[-1]
        if not math.isfinite(z):
            # Defensive: the engine keeps the pipeline finite; treat any
            # residual non-finite z as "no usable signal".
            return _flat(ts, "flat-no-signal", components)

        # 8. Contract conversion through the single core implementation.
        price = close[-1]
        contracts = to_contracts(
            z=z,
            price=price,
            cap=h.cap,
            instrument=self.instrument,
            limits=cfg.limits,
        )
        # Telemetry only: the un-clipped rounded count decides "cap-limited".
        l_max = max_contracts_at(price=price, instrument=self.instrument, limits=cfg.limits)
        rounded = round(z / h.cap * l_max)  # Python round: half-to-even

        # 9. Reason.
        if abs(rounded) > cfg.limits.max_contracts:
            reason = "cap-limited"
        elif contracts == 0:
            reason = "flat-no-signal"
        else:
            reason = "signal"

        return TargetPosition(
            ts=ts,
            target_contracts=contracts,
            z_target=z,
            reason=reason,
            components=components,
        )


def default_seed_portfolio_config() -> PortfolioConfig:
    """Seed configuration for research bootstrap: the 6 verified seed
    expressions with equal weights 1/6 and the ``HarnessParams``/``AccountLimits``
    defaults (100m VND capital, 5% margin rate, 0.5 safety factor,
    10-contract cap). The live runner does NOT use this fallback: it builds
    the portfolio from the pool weights artifact (see
    :func:`portfolio_config_from_pool`)."""
    n = len(SEED_EXPRESSIONS)
    return PortfolioConfig(
        expressions=SEED_EXPRESSIONS,
        weights=tuple(1.0 / n for _ in range(n)),
    )


def portfolio_config_from_pool(
    artifact: WeightsArtifact,
    pool: AlphaPool | None = None,
    instrument: Instrument | None = None,
    *,
    limits: AccountLimits | None = None,
) -> PortfolioConfig:
    """Build a live ``PortfolioConfig`` from the research weights artifact.

    Parameters
    ----------
    artifact : WeightsArtifact
        The combined-pool weights artifact loaded with
        ``WeightsArtifact.load()`` (default root ``data/pool``). Keys are
        ``alpha_id`` values produced by the research flow.
    pool : AlphaPool | None
        The research pool carrying each alpha's DSL. When given, every
        artifact weight key must match a pool entry ``alpha_id`` and the
        configured expressions are the matched DSL strings (sorted key
        order). When ``None``, artifact keys are taken AS the expressions —
        only valid for hand-authored weights files keyed by DSL strings.
    instrument : Instrument | None
        When given, cross-checked against the artifact's recorded window
        instrument (if the artifact carries one) so a weights file fitted on
        another instrument cannot reach the live runner.
    limits : AccountLimits | None
        Account sizing limits from the runtime config (capital etc.);
        ``None`` keeps the ``AccountLimits`` defaults.

    Returns
    -------
    PortfolioConfig
        Expressions/weights from the artifact (joined through the pool when
        given) with the given limits.

    Raises
    ------
    ValueError
        If the artifact has no weights, a weight key has no matching pool
        entry, instrument metadata mismatches, or an instrument mismatch
        against ``instrument``.
    """
    if not artifact.weights:
        raise ValueError(
            f"weights artifact at {artifact.generated!r} carries no weights; "
            "run the research combine flow to produce data/pool/weights.json"
        )
    window = artifact.window
    if instrument is not None and window is not None:
        window_symbol = str(window.instrument_id).split(".", 1)[0]
        if window_symbol.casefold() != instrument.symbol.casefold():
            raise ValueError(
                f"weights artifact window instrument {window_symbol!r} does not "
                f"match configured instrument {instrument.symbol!r}"
            )
    if pool is None:
        expressions = tuple(artifact.weights)
    else:
        dsl_by_id = {entry.alpha_id: entry.dsl for entry in pool.entries}
        missing = [key for key in artifact.weights if key not in dsl_by_id]
        if missing:
            raise ValueError(
                f"weights artifact keys absent from pool: {missing}; "
                "re-deliver the pool or refit the weights"
            )
        expressions = tuple(dsl_by_id[key] for key in sorted(artifact.weights))
    return PortfolioConfig(
        expressions=expressions,
        weights=tuple(artifact.weights[key] for key in sorted(artifact.weights)),
        limits=limits if limits is not None else AccountLimits(),
    )
