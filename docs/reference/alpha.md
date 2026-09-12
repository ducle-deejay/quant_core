# Reference: alpha

`quantcore.alpha` — the Alpha Researcher module. WorldQuant-style workflow:
hand-written seed -> single-alpha evaluation -> screening -> GA mining from
passing seeds -> delivery into the pool. Every entry point takes its bars
explicitly as a `core.data.BarFrame`; nothing is loaded internally. Scores
are z-units; PnL metrics are in canonical composite units (position x
return per bar); `cost_drag_pct` is a percent value.

## `GateCriteria`

```python
@dataclass(frozen=True)
class GateCriteria(
    min_abs_ic: float = 0.02,
    max_cost_drag_pct: float = 40.0,
    min_net_sharpe: float = 0.8,
    min_icir: float = 0.3,
    min_positive_blocks_pct: float = 60.0,
    ic_horizons: tuple[int, ...] = (1, 5, 15),
    ic_window: int = 480,
    walk_forward_block_days: int = 5,
    ann_factor: float = 250.0,
    bars_per_day: int = 240,
    sharpe_variance: float = 0.25,
) -> None
```

Evaluation/screening gate thresholds for one alpha.

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `min_abs_ic` | float | z-units vs returns (rank correlation) | Minimum absolute mean IC. |
| `max_cost_drag_pct` | float | percent | Maximum cost drag (40.0 == 40%). |
| `min_net_sharpe` | float | — | Minimum annualized net Sharpe of daily PnL. |
| `min_icir` | float | — | Minimum IC information ratio (mean/std of per-block rank ICs). |
| `min_positive_blocks_pct` | float | percent | Minimum share of positive walk-forward blocks. |
| `ic_horizons` | tuple[int, ...] | bars | IC ladder horizons. |
| `ic_window` | int | bars | Block length for ICIR and IC estimation windows. |
| `walk_forward_block_days` | int | trading days | Walk-forward block length. |
| `ann_factor` | float | — | Annualization factor for daily-observation statistics. |
| `bars_per_day` | int | bars/day | Bars per trading day for daily aggregation. |
| `sharpe_variance` | float | — | Trial-Sharpe variance for the deflated threshold. |

## `AlphaConfig`

```python
@dataclass(frozen=True)
class AlphaConfig(
    harness: HarnessParams = field(default_factory=HarnessParams),
    gate: GateCriteria = field(default_factory=GateCriteria),
    ga_population_size: int = 100,
    ga_generations: int = 20,
    ga_seed: int = 42,
    n_trials: int = 0,
    record_trial: bool = False,
) -> None
```

Everything one research call needs; every field has a default.

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `harness` | HarnessParams | — | Canonical simulation parameters. |
| `gate` | GateCriteria | — | Evaluation/screening thresholds. |
| `ga_population_size` / `ga_generations` / `ga_seed` | int | — | GA parameters used by `mine_seeds`; `ga_seed` gives deterministic breeding. |
| `n_trials` | int | — | Effective trial count; `> 0` wires the deflated-Sharpe check into the gate. Trial counting is the caller's responsibility (use `record_trial=True`). |
| `record_trial` | bool | — | When True, every evaluation is appended to the trial ledger. |

## `ScreenResult`

```python
@dataclass(frozen=True)
class ScreenResult(funnel: dict, tear_sheets: list[TearSheet], survivors: list[str]) -> None
```

| Field | Type | Meaning |
|---|---|---|
| `funnel` | dict | `total_candidates`, `ic_pass_count`, `drag_pass_count` (engine screening gates), `survivor_count` (full-gate verdict IN). |
| `tear_sheets` | list[TearSheet] | One per candidate, input order. |
| `survivors` | list[str] | Canonical DSL strings of full-gate survivors. |

## `validate_seed`

```python
def validate_seed(dsl: str) -> str
```

Return the canonical DSL form; raises `ValueError` on invalid syntax.

## `score`

```python
def score(expressions: list[str], close: list[float], volume: list[float]) -> list[list[float]]
```

Batch-score expressions over close/volume — one engine call, one row per
expression; the scoring primitive for custom `ga_fitness` functions.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `expressions` | list[str] | — | DSL expressions (canonicalized first for safety). |
| `close` | list[float] | VND per index point | Close prices, one per bar. |
| `volume` | list[float] | contracts | Volumes, one per bar. |

Returns: one score series (z-units) per expression, input order.

## `evaluate_seed`

```python
def evaluate_seed(dsl: str, bars: BarFrame, config: AlphaConfig | None = None) -> TearSheet
```

Single-alpha evaluation: canonicalize -> batch score -> sanitize ->
canonical position -> net/gross PnL -> metrics (Sharpe, max drawdown, cost
drag, IC ladder, walk-forward, ICIR) -> gate verdict `"IN"`/`"OUT"` with
failing reasons. Costs use the bar instrument's cost model
(`Instrument.cost.cost_per_side_frac`). With `config.record_trial=True` the
evaluation is appended to the trial ledger.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `dsl` | str | — | Seed expression in the canonical DSL. |
| `bars` | BarFrame | — | Bar window (close/volume feed the engine). |
| `config` | AlphaConfig \| None | — | Defaults to `AlphaConfig()`. |

Returns: `TearSheet` (metrics, verdict, reasons, provenance). Raises:
`ValueError` — invalid DSL syntax or an expression producing no finite
values (fields absent from the data; only close/volume exist in the
research catalog).

Gate checks (reason names in `TearSheet.reasons`): `ic` (strict `>`),
`cost_drag` (strict `<`), `net_sharpe` (strict `>`), `walk_forward` (not
applicable below 2 blocks), `icir` (not applicable when None), plus
`deflated_sharpe` when `config.n_trials > 0`. Cost drag uses the engine
convention `cost / |gross|` (always non-negative).

## `screen_batch`

```python
def screen_batch(seeds: list[str], bars: BarFrame, config: AlphaConfig | None = None) -> ScreenResult
```

Evaluate a batch and report the screening funnel. Every candidate is
recorded in the trial ledger when `config.record_trial=True` (the funnel is
where trials are counted). `survivor_count` counts FULL-gate survivors,
while `ic_pass_count`/`drag_pass_count` are the engine screening counts.

Raises: `ValueError` — empty seed list.

## `mine_seeds`

```python
def mine_seeds(seeds: list[str], bars: BarFrame, config: AlphaConfig | None = None) -> list[str]
```

Breed the GA from evaluation-passing seeds (WorldQuant-style). Uses the
`ga_fitness` registry `"engine"` method with `config.ga_population_size` /
`ga_generations` / `ga_seed`. Every returned element is validated,
canonicalized and deduplicated (custom fitnesses are not trusted; the
engine path is idempotent here).

Returns: the final population's canonical DSL strings ranked best-first,
deterministic for a fixed `ga_seed`. Raises: `ValueError` — empty seed
list, invalid seed syntax, or a fitness returning non-string entries.

## `build_spec_sheet`

```python
def build_spec_sheet(sheet: TearSheet, bars: BarFrame) -> SpecSheet
```

Build the PASS artifact consumed by the Portfolio Researcher, the
divergence gauges and the live kill criteria. Holding period = ladder
horizon with max |mean IC|; expected ICs = the full ladder; capacity = 5%
of mean daily volume (documented participation heuristic); kill criteria =
rolling 20-day IC below zero for ten consecutive days (the documented
example).

| Parameter | Type | Meaning |
|---|---|---|
| `sheet` | TearSheet | Evaluation tear sheet (must carry `ic_ladder` metrics). |
| `bars` | BarFrame | The same window the tear sheet was evaluated on (volume feeds capacity). |

Returns: `SpecSheet` including `expected_ic` and the default
`cost_model_bps`.

## `deliver`

```python
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
) -> PoolEntry
```

Deliver an IN-verdict alpha into the in-memory pool: builds the `PoolEntry`
(schema_version `"2"`, embedding both sheets) and adds it to `pool`.
SAVING is the caller's explicit `pool.save()`.

| Parameter | Type | Meaning |
|---|---|---|
| `pool` | AlphaPool | Pool to append to. |
| `sheet` | TearSheet | Evaluation tear sheet; verdict must be `"IN"`. |
| `spec` | SpecSheet | Expectation sheet (`build_spec_sheet`). |
| `alpha_id` | str \| None | Override id; defaults to the deterministic id of the canonical DSL. |
| `author` | str | Author tag. |
| `tags` | tuple[str, ...] | Free-form tags. |
| `family` | str \| None | Mining family label (GA lineage). |
| `source` | str | Provenance (`"seed"` or `"ga"`). |

Returns: the added `PoolEntry`. Raises: `ValueError` — verdict not `"IN"`.

## `score_model`

```python
def score_model(model: str | object, close: list[float], volume: list[float]) -> list[float]
```

Score one observation window through the quantitative-model contract.
`model` is a registered `quantitative_models` name or any object providing
`score(close, volume) -> list[float]`. Returns one score per bar (z-units
where the model produces them). Raises: `ValueError` — empty/mismatched
inputs, wrong output length, or no finite scores; `TypeError` — `model` is
neither a registered name nor a score-providing object.

## `EngineQuantitativeModel`

```python
class EngineQuantitativeModel:
    def __init__(self, dsl: str) -> None
    def score(self, close: Sequence[float], volume: Sequence[float]) -> list[float]
    __call__ = score
```

Thin model adapter over the Rust expression evaluator; `dsl` is
canonicalized once at construction (`validate_expression_py`). Instances
are callable and provide `score`, satisfying the `quantitative_models`
plain-callable contract.

## Registries

- `ga_fitness = Registry("ga_fitness")` — built-in `"engine"` (Rust GA,
  fixed fitness = mean score x next-bar return). Custom fitness contract:
  `fn(seeds, close, volume, population_size, generations, seed) ->
  list[str]`, using `score` as the scoring primitive.
- `quantitative_models = Registry("quantitative_models")` — built-in
  `"engine_close"` (`EngineQuantitativeModel("close")`). Other expressions
  construct `EngineQuantitativeModel(dsl)` explicitly; no expression is
  selected by an implicit default.

See [../conventions.md](../conventions.md#extension-registries).
