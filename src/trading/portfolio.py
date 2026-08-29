"""Portfolio orchestration for the live wiring phase (milestone 1, workstream A).

Pure ``alpha_core`` + stdlib: one bar buffer in, one signed target position
out, per the ``Portfolio`` protocol in ``trading.contracts``. No Nautilus
dependency. Implements canon stages STG-1-CANONICAL-SIM (score -> position),
STG-5-POSITION-CONSTRUCTION (vol targeting -> target) and the milestone-1
contract conversion recorded in decision note DEC-008.

Per-bar algorithm (deterministic; the same input always yields the same
``TargetPosition``):

1. Shape guards. ``bars`` must carry ``"close"`` and ``"volume"`` lists of
   equal, non-empty length. A buffer shorter than ``z_window + WARMUP_MARGIN``
   (800 bars with the default ``z_window = 480``) is not warmed up yet and
   yields a flat target with reason ``"warmup"``. Missing/incompatible keys
   are treated as invalid input.
2. Value guards. Any non-finite close/volume value, or any non-positive
   close (a zero/negative index price makes returns and the margin
   conversion meaningless), yields a flat target with reason
   ``"invalid-input"``.
3. Scoring. Every configured expression is evaluated over the full buffers
   in ONE ``execute_batch_py`` call (the whole expression list, never one
   call per alpha) -> a score matrix with one row per expression.
4. NaN sanitisation. ``execute_batch_py`` emits NaN during each rolling
   operator's warmup by engine contract (operators.rs: first ``window - 1``
   bars are NaN), and the ``canonical_map_py`` binding rejects any non-finite
   score. The Rust core ``canonical_map`` handles this with
   ``sanitize_scores`` (forward-fill of non-finite values; all-NaN maps to
   zeros), so this module mirrors exactly that semantics in Python before
   calling ``canonical_map_py`` (see GAP-1 in the integrator handoff).
5. Canonical mapping. Each sanitised score row is mapped with
   ``canonical_map_py(score, span, z_window, band, cap, bars_per_day)`` from
   ``config.harness`` -> a per-alpha position series in z units. The current
   per-alpha position is the last element and is recorded in ``components``
   under its expression key (telemetry).
6. Composite z. ``composite_score_py`` is applied to the per-alpha position
   series with the config weights normalised to sum to 1 (the engine
   function is reused rather than recomputed by hand, for research/live
   parity); the current composite z is the last element.
7. Volatility targeting. A rolling realised-vol series of the underlying
   close returns (simple returns ``close[t]/close[t-1] - 1``, sample
   standard deviation ddof=1 over a trailing ``VOL_WINDOW = 20`` bar window,
   annualised by ``sqrt(bars_per_day)``; windows with fewer than two samples
   or zero variance are 0.0, matching the engine's ``ts_std`` convention) is
   passed to ``vol_target_py(composite, vol_est, config.vol_target,
   config.vol_floor)``. ``vol_target`` is an annualised fraction and
   ``vol_est`` is annualised, so the target/estimate ratio is scale-
   invariant. The current target z is the last element.
8. Contract conversion (DEC-008)::
       L_max = floor(capital_vnd * safety_factor / (margin_rate * price * 100_000))
       raw   = z / cap * L_max
       contracts = round(raw)          # Python round, half-to-even
       contracts = clip(contracts, -max_contracts, +max_contracts)
   with ``price`` = last close and ``cap`` = ``harness.cap``. ``z_target``
   on the result carries the pre-rounding z (the vol-targeted z).
9. Reason. ``"warmup"`` (buffer not yet long enough), ``"invalid-input"``
   (malformed/non-finite/non-positive bars or an engine failure), then
   ``"cap-limited"`` when the un-clipped rounded contract count exceeds
   ``max_contracts``, ``"flat-no-signal"`` when it rounds to zero or the z
   is degenerate, else ``"signal"``.

Frozen-canon/ledger context: market facts are the VN30F1M contract
multiplier 100,000 VND per index point and the entrade 5% margin rate
(observation notes OBS-009/OBS-010); the milestone-1 cost model is the
scalar ``HarnessParams.cost_per_side`` (decision note DEC-006); the
contract conversion formula is decision note DEC-008.
"""

from __future__ import annotations

import math
from datetime import datetime

import alpha_core

from trading.contracts import Portfolio, PortfolioConfig, TargetPosition

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


def _sanitize_scores(series: list[float]) -> list[float]:
    """Forward-fill non-finite score values, mirroring the engine's
    ``sanitize_scores``: leading non-finite values take the first finite
    value, interior ones carry the last finite value forward, and an
    all-non-finite series maps to zeros."""
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


def _rolling_vol(close: list[float], window: int, bars_per_day: int) -> list[float]:
    """Annualised rolling realised vol of simple close returns.

    ``vol_est[t] = sample_std(r[t-window+1 .. t]) * sqrt(bars_per_day)`` with
    ``r[0] = 0.0`` and ``r[t] = close[t]/close[t-1] - 1``. Trailing windows
    with fewer than two samples yield 0.0 (the engine's ``ts_std`` yields NaN
    there; 0.0 is used so the vol-target zero guard produces a flat output
    and the series stays finite for ``vol_target_py``)."""
    n = len(close)
    rets = [0.0] * n
    for t in range(1, n):
        rets[t] = close[t] / close[t - 1] - 1.0
    scale = math.sqrt(bars_per_day)
    out: list[float] = []
    for t in range(n):
        win = rets[max(0, t - window + 1) : t + 1]
        if len(win) < 2:
            out.append(0.0)
            continue
        mean = sum(win) / len(win)
        var = sum((v - mean) * (v - mean) for v in win) / (len(win) - 1)  # ddof=1
        out.append(math.sqrt(var) * scale)
    return out


class PortfolioOrchestrator(Portfolio):
    """Implements the ``Portfolio`` protocol: bars in, one target out.

    Pure ``alpha_core`` calls plus stdlib math; every step is deterministic.
    The configuration (expressions, weights, harness and sizing parameters)
    is validated once at construction so per-bar evaluation cannot fail on
    configuration errors.
    """

    def __init__(self, config: PortfolioConfig) -> None:
        self.config = config
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
        if h.cost_per_side < 0.0:
            raise ValueError("harness cost_per_side must be non-negative")
        if not math.isfinite(config.vol_target) or config.vol_target <= 0.0:
            raise ValueError("vol_target must be a positive finite fraction")
        if config.vol_floor is not None and (
            not math.isfinite(config.vol_floor) or config.vol_floor <= 0.0
        ):
            raise ValueError("vol_floor must be None or a positive finite fraction")
        if config.capital_vnd <= 0.0 or config.margin_rate <= 0.0:
            raise ValueError("capital_vnd and margin_rate must be positive")
        if config.safety_factor < 0.0:
            raise ValueError("safety_factor must be non-negative")
        if config.max_contracts < 0:
            raise ValueError("max_contracts must be non-negative")
        return weights

    def compute_target(
        self,
        bars: dict[str, list[float]],
        ts: datetime,
    ) -> TargetPosition:
        """One bar buffer in, one signed ``TargetPosition`` out (see module
        docstring for the exact deterministic pipeline)."""
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
        except ValueError as exc:
            # Defensive: precluded by init-time validation and the guards
            # above; degrade to flat rather than crash the live loop.
            return _flat(ts, "invalid-input")

        # 4-5. Sanitise warmup NaN and map each row to canonical positions.
        positions: list[list[float]] = []
        components: dict[str, float] = {}
        for expr, row in zip(cfg.expressions, matrix):
            sane = _sanitize_scores(row)
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
        vol_est = _rolling_vol(list(close), VOL_WINDOW, h.bars_per_day)
        vol_series = alpha_core.vol_target_py(
            composite, vol_est, cfg.vol_target, cfg.vol_floor
        )
        z = vol_series[-1]
        if not math.isfinite(z):
            # Defensive: the engine keeps the pipeline finite; treat any
            # residual non-finite z as "no usable signal".
            return _flat(ts, "flat-no-signal", components)

        # 8. Contract conversion (DEC-008).
        price = close[-1]
        l_max = math.floor(
            cfg.capital_vnd * cfg.safety_factor / (cfg.margin_rate * price * 100_000.0)
        )
        raw = z / h.cap * l_max
        rounded = round(raw)  # Python round: half-to-even, deterministic
        contracts = max(-cfg.max_contracts, min(cfg.max_contracts, rounded))

        # 9. Reason.
        if abs(rounded) > cfg.max_contracts:
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
    """Milestone-1 seed configuration: the 6 verified seed expressions with
    equal weights 1/6 and the ``HarnessParams``/sizing defaults (100m VND
    capital, 5% entrade margin, 0.5 safety factor, 10-contract cap)."""
    n = len(SEED_EXPRESSIONS)
    return PortfolioConfig(
        expressions=SEED_EXPRESSIONS,
        weights=tuple(1.0 / n for _ in range(n)),
    )
