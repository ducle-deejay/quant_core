# Reference: portfolio

`quantcore.portfolio` — the Portfolio Researcher module. Consumes the
research pool, scores it over a bar window, combines scores into a
composite, refits allocation weights on a cadence and produces the health
report. Position sizing is owned by the risk role. Scores/composites are
z-units; Sharpe/IC/r-squared are scale-free; weights are fractions summing
to one.

Combination parity: the composite series always comes from the Rust engine
(`alpha_core.composite_score_py`); research-side weight derivation mirrors
the engine's capped-simplex inverse-vol algorithm (min `MIN_WEIGHT = 0.01`,
max `MAX_WEIGHT = 0.50`, sum 1), so reported weights agree with what the
engine used.

## `score_pool`

```python
def score_pool(pool: AlphaPool, bars: BarFrame) -> dict[str, np.ndarray]
```

Score every pool alpha's canonical DSL over the bars (combination input).
All expressions run in ONE `execute_batch_py` call.

Rows are returned RAW — engine contract: the first `window - 1` bars of
each rolling operator are NaN — so the combination sees exactly what the
canonical harness sees; `combine` standardizes internally. Callers must not
forward-fill here: sanitizing changes vol estimates and therefore the
combination weights.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `pool` | AlphaPool | — | Research pool (entries carry `dsl`). |
| `bars` | BarFrame | — | Bar window to score over. |

Returns: `{alpha_id: raw score series}` (z-units); an empty pool yields
`{}`.

## `combine`

```python
def combine(
    scores: dict[str, np.ndarray],
    method: str = DEFAULT_COMBINE_METHOD,   # "inverse_vol"
    weights: dict[str, float] | None = None,
    *,
    window,
) -> Composite
```

Combine per-alpha score series into one composite (z-units). Built-ins
dispatch through the `combine_methods` registry (real dispatch: replacing a
registration changes this function's output). Explicit `weights` bypass the
method entirely (the composite's `method` is recorded as `"explicit"`);
they are normalized to sum to one, exactly like the engine does inside
`composite_score_py`, and applied to the standardized rows.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `scores` | dict[str, numpy.ndarray] | z-units | alpha_id -> score series, all equal length. Raw `score_pool` rows (warmup NaN included) are the canonical input. |
| `method` | str | — | Registry key in `combine_methods`; built-ins `"equal_weight"`, `"inverse_vol"`. |
| `weights` | dict[str, float] \| None | fractions | Explicit per-alpha weights; overrides `method` when given. |
| `window` | core.artifacts.Window (keyword-only) | — | Bar window the scores are aligned to; recorded on the Composite for downstream provenance validation (risk). |

Returns: `Composite` (alpha_ids sorted, normalized weights, composite
scores, window, method label). Raises: `ValueError` — empty/ragged scores,
unknown method, explicit weights not covering exactly the score keys, a
zero/non-finite explicit-weight sum, or a registered method returning a
malformed result.

## `equal_weight`, `inverse_vol`

```python
def equal_weight(scores: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, float]]
def inverse_vol(scores: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, float]]
```

Engine-backed built-ins registered in `combine_methods`
(`source="engine"`). Both standardize rows and run the weighted sum through
`alpha_core.composite_score_py`. Standardization is PARITY-LOCKED with the
pre-redesign system: the row's std runs over the WHOLE row including warmup
NaN, so any non-finite entry makes the std non-finite and the ENTIRE row
maps to zeros. `equal_weight` uses `1/N`; `inverse_vol` derives
`w_i = 1/std_i` from the raw series (the risk measure, sample stddev with
n-1 denominator) with the capped-simplex projection — the volatility
estimate is poisoned by ANY non-finite entry (returns None -> weight 0,
excluded from the budget); a pool where no alpha has a usable estimate
falls back to equal weights; a lone eligible alpha takes the full budget
(even past `MAX_WEIGHT` — sum-to-one wins over the caps). With the seed
DSLs only `close - ewma(close, 8)` produces a NaN-free row, so it is the
sole eligible alpha and the composite is its standardized row.

Returns: `(composite, weights)` — composite in z-units, fractions per
alpha_id (sum 1).

## `refit_weights`

```python
def refit_weights(pool: AlphaPool, bars: BarFrame, method: str = DEFAULT_COMBINE_METHOD) -> WeightsArtifact
```

Weight-refit cadence: scores the pool (one engine batch, raw rows) and
resolves the weights through the `combine_methods` registry. Returns the
UNSAVED artifact — saving is the caller's explicit
`WeightsArtifact.save()` (the handoff artifact consumed by the live
`PortfolioConfig`).

| Parameter | Type | Meaning |
|---|---|---|
| `pool` | AlphaPool | Research pool (non-empty). |
| `bars` | BarFrame | Refit window (full window; slice the BarFrame for a trailing refit). |
| `method` | str | Registry key in `combine_methods`. |

Returns: `WeightsArtifact` (`generated` ISO date, `method`, fractions per
alpha_id, `window`). Raises: `ValueError` — empty pool or unknown method.

## `PortfolioHealth`, `health_report`

```python
@dataclass(frozen=True)
class PortfolioHealth(
    generated: str,
    pool_size: int,
    bars: int,
    window_days: int,
    full_sample_sharpe: float,
    max_drawdown: float,
    last_window_sharpe: float,
    window_return: float,
    rolling_mean_ic: float,
    verdict: str,
    units: str,
) -> None
```

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `generated` | str | — | ISO-8601 UTC timestamp. |
| `pool_size` / `bars` / `window_days` | int | — | Composite size; bar count; trailing window (30 days). |
| `full_sample_sharpe` | float | — | Annualized Sharpe of daily net PnL (full sample). |
| `max_drawdown` | float | — | Most negative peak-to-trough drawdown of the daily equity curve. |
| `last_window_sharpe` | float | — | Same Sharpe over the last 30 calendar days of bars. |
| `window_return` | float | canonical composite units | Sum of daily net PnL over the same window. |
| `rolling_mean_ic` | float | — | Pearson correlation of composite vs next-bar returns over the last window's aligned finite pairs (0.0 when undefined). |
| `verdict` | str | — | `"refit"` when `last_window_sharpe < 0` or `rolling_mean_ic < 0.05`, else `"ok"`. |
| `units` | str | — | Units note (PnL in canonical composite units, NOT capital fractions). |

```python
def health_report(composite: Composite, bars: BarFrame) -> PortfolioHealth
```

Monthly allocation-review input; in-memory only, never auto-saved.
Pipeline: composite scores -> `canonical_map_py` position ->
`compute_pnl_py` net per-bar PnL (cost = the bar instrument's cost model)
-> daily sums. Raises: `ValueError` — composite score length differs from
the bar count.

## `OrthoReport`, `orthogonalize`

```python
@dataclass(frozen=True)
class OrthoReport(
    residual_sharpe: float,
    residual: list[float],
    betas: list[float],
    r_squared: float,
    verdict: str,
    note: str,
) -> None
```

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `residual_sharpe` | float | — | Annualized Sharpe of the residual PnL (daily-aggregated, engine `sharpe_py`). |
| `residual` | list[float] | canonical PnL units | Candidate minus pool projection. |
| `betas` | list[float] | — | OLS betas of the candidate on the pool series, pool order = sorted alpha ids. |
| `r_squared` | float | — | Share of candidate variance explained by the pool (0.0 for a constant candidate). |
| `verdict` | str | — | `"INCREMENTAL"` when the finite residual Sharpe exceeds `min_residual_sharpe`, else `"REDUNDANT"`. |
| `note` | str | — | One-line rationale. |

```python
def orthogonalize(candidate: np.ndarray, scores: dict[str, np.ndarray], min_residual_sharpe: float = 0.0) -> OrthoReport
```

Orthogonalization verdict for one candidate vs a pool of series. The
canonical input is per-bar NET PnL series (candidate + pool): build them
with the canonical pipeline (batch score -> sanitize -> `canonical_map_py`
-> `compute_pnl_py`). `orthogonalize_py` regresses the candidate on the
pool series; the residual's ANNUALIZED Sharpe decides the verdict.
`min_residual_sharpe` defaults to 0.0 (sign test).

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `candidate` | numpy.ndarray | canonical PnL | Candidate series. |
| `scores` | dict[str, numpy.ndarray] | canonical PnL | Pool series keyed by alpha_id; regression order = sorted ids. |
| `min_residual_sharpe` | float | — | Admission threshold for the residual Sharpe. |

## Registry

`combine_methods = Registry("combine_methods")` — `equal_weight` and
`inverse_vol` registered at import with `source="engine"`. Practitioners
register research methods (`source="python"`) with the contract
`fn(scores: dict[str, numpy.ndarray]) -> tuple[numpy.ndarray,
dict[str, float]]` (composite in z-units + derived weights). Registry
dispatch is the REAL path for built-ins: replacing a registration changes
`combine`/`refit_weights` output.

Module constants: `MIN_WEIGHT = 0.01`, `MAX_WEIGHT = 0.50`,
`DEFAULT_COMBINE_METHOD = "inverse_vol"`,
`DEFAULT_HEALTH_WINDOW_DAYS = 30`, `MIN_HEALTH_MEAN_IC = 0.05`.
