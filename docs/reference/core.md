# Reference: core

The bottom layer: data access, cross-role contracts, score-to-contracts
mapping, the expiry rule, artifact schemas and IO, and the extension
registries. All public names re-exported from `core` (`src/core/__init__.py`).
Units and naming: [../conventions.md](../conventions.md).

## Package constants

```python
core.data.DEFAULT_CATALOG_PATH  # Path("/Users/ducle/repos/nox_system/data/catalog"); env override QUANTCORE_CATALOG
core.data.DEFAULT_BAR_TYPE      # "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL"
core.data.DEFAULT_INSTRUMENT_ID # "VN30F1M.HNX"
core.artifacts.DEFAULT_RESEARCH_DIR  # <repo>/data/research
core.artifacts.DEFAULT_POOL_DIR      # <repo>/data/pool
core.artifacts.POOL_SCHEMA_VERSION   # "2"
core.expiry.VN_TZ               # ZoneInfo("Asia/Ho_Chi_Minh")
core.expiry.EXPIRY_HOUR_LOCAL   # 14
core.expiry.EXPIRY_MINUTE_LOCAL # 0
```

---

## Data access (`core.data`)

### `DataConfig`

```python
@dataclass(frozen=True)
class DataConfig:
    instrument_id: str = DEFAULT_INSTRUMENT_ID
    bar_type: str = DEFAULT_BAR_TYPE
    start: str | None = None
    end: str | None = None
```

Data resolution for every module entry point. All fields optional; `None`
dates mean full history for the default instrument/bar type.

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `instrument_id` | str | — | Nautilus instrument id. |
| `bar_type` | str | — | Nautilus bar type string. |
| `start` | str \| None | UTC (ISO) | Inclusive range start; `None` = open. |
| `end` | str \| None | UTC (ISO) | Inclusive range end; `None` = unbounded. |

Naive ISO strings are localized to UTC; aware ones are converted.

### `BarFrame`

```python
@dataclass(frozen=True)
class BarFrame:
    ts: pd.DatetimeIndex
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    instrument_id: str
    bar_type: str
```

One instrument's OHLCV bars, aligned and validated. `ts` is UTC, sorted
ascending; the arrays are float64. Prices in VND per index point, volume in
contracts.

| Member | Signature | Meaning |
|---|---|---|
| `window` (property) | `-> Window` | The `Window` covered by this frame (first/last ts, bar count). |
| `from_dataframe` (classmethod) | see below | Build from a DataFrame with columns `ts, open, high, low, close, volume`; any tz accepted, normalized to UTC. |
| `close_list` | `close_list() -> list[float]` | Close column as a list (engine feeders). |
| `volume_list` | `volume_list() -> list[float]` | Volume column as a list (engine feeders). |

```python
@classmethod
def from_dataframe(
    cls,
    df: pd.DataFrame,
    *,
    instrument_id: str = "",
    bar_type: str = "",
) -> "BarFrame"
```

`instrument_id` / `bar_type` are left empty by default (the DataFrame
carries no identity); pass them when known. Raises `ValueError` on missing
columns, an empty frame, tz-naive `ts`, or unsorted `ts`.

Raises (`from_dataframe`): `ValueError` — required columns missing, empty
frame, tz-naive `ts`, or unsorted `ts`.

### `CatalogClient`

```python
class CatalogClient:
    def __init__(self, root: Path | None = None) -> None
    def bars(self, config: DataConfig | None = None) -> BarFrame
    def ticks(self, instrument_id: str, start: str | pd.Timestamp | None = None, end: str | pd.Timestamp | None = None) -> pd.DataFrame
    def depth(self, instrument_id: str, start: str | pd.Timestamp | None = None, end: str | pd.Timestamp | None = None) -> pd.DataFrame
```

Read-only accessor for the Nautilus parquet research catalog.
`root=None` uses `DEFAULT_CATALOG_PATH`. The `root` property returns the
catalog root. `nautilus_trader` is imported lazily inside the methods.

`bars` — one instrument's OHLCV bars as a validated `BarFrame` (sorted
ascending, UTC). `config=None` means full VN30F1M 1-minute history.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `config` | DataConfig \| None | — | Instrument/bar-type/date resolution; `None` uses the defaults. |

Returns: `BarFrame`. Raises: `FileNotFoundError` — catalog root missing;
`ValueError` — no bars in range.

`ticks` — trade ticks as a DataFrame with columns `ts` (UTC), `price`
(float), `size` (float), `aggressor_side` (`"BUYER"`, `"SELLER"` or
`"NO_AGGRESSOR"`), sorted by `ts`.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `instrument_id` | str | — | Nautilus instrument id, e.g. `"VN30F1M.HNX"` (ticks/depth live under `"41I1G9000.HNX"`). |
| `start` | str \| pandas.Timestamp \| None | UTC | Inclusive range start; `None` = open. |
| `end` | str \| pandas.Timestamp \| None | UTC | Inclusive range end; `None` = unbounded. |

Raises: `FileNotFoundError` — catalog root missing.

`depth` — 10-level order-book depth as a long-format DataFrame with columns
`ts` (UTC), `level` (int 0-9, 0 = best), `side` (`"bid"` | `"ask"`),
`price` (float), `size` (float), sorted by `ts`. Same parameters and raise
as `ticks`.

---

## Instruments (`core.instruments`, re-exported by `core.contracts`)

Definitions are read from
`src/market_data/instrument_definitions/<symbol>.hnx.json`
(`INSTRUMENT_DEFINITIONS_DIR`); `core` is the only code allowed to read
them.

### `Instrument`

```python
@dataclass(frozen=True)
class Instrument:
    symbol: str
    venue: str
    multiplier: float
    tick_size: float
    cost: CostModel = field(default_factory=CostModel)

    @classmethod
    def load(cls, symbol: str) -> "Instrument"
```

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `symbol` | str | — | Exchange symbol, e.g. `"VN30F1M"`. |
| `venue` | str | — | Venue code as used in Nautilus instrument ids, e.g. `"HNX"`. |
| `multiplier` | float | VND per index point | Contract multiplier (100,000.0 for VN30F1M). |
| `tick_size` | float | VND per index point | Minimum price increment (0.1). |
| `cost` | CostModel | — | Per-side cost model. |

`load` (cached per symbol, case-insensitive) reads the definition JSON,
falling back to the file's `exchange` key when `venue` is absent.
Raises: `FileNotFoundError` — no definition file for `symbol`; `ValueError`
— required keys missing.

### `CostModel`

```python
@dataclass(frozen=True)
class CostModel:
    cost_per_side_frac: float = 0.000229
    reference_price: float = 1500.0
    source: str = "DEC-006-milestone1"
```

Per-side cost at a reference price: fee + half-spread + buffer =
1.461 + 0.333 + 0.5 bp = 2.294 bp per side (`cost_per_side_frac` is a
fraction of notional). Scalar until a two-part model lands.

---

## Contracts (`core.contracts`)

### `Account`

```python
class Account(StrEnum):
    DEMO = "demo"
    LIVE = "live"
```

Trading account routing target (paper/demo vs live).

### `HarnessParams`

```python
@dataclass(frozen=True)
class HarnessParams:
    span: int = 8
    z_window: int = 480
    band: float = 0.35
    cap: float = 2.0
    bars_per_day: int = 240
```

Canonical harness parameters (Component 1). `band` in z-units (no-trade
band width), `cap` in z-units (z mapped to the maximum position),
`bars_per_day` bars per trading day.

### `AccountLimits`

```python
@dataclass(frozen=True)
class AccountLimits:
    capital_vnd: float = 100_000_000.0
    safety_factor: float = 0.5
    margin_rate: float = 0.05
    max_contracts: int = 10
```

Account-level sizing limits shared by portfolio and risk. `margin_rate` is
the entrade deposit ratio (5%) as a fraction.

### `PortfolioConfig`

```python
@dataclass(frozen=True)
class PortfolioConfig:
    expressions: tuple[str, ...]
    weights: tuple[float, ...]
    harness: HarnessParams = field(default_factory=HarnessParams)
    vol_target: float = 0.1
    vol_floor: float | None = None
    limits: AccountLimits = field(default_factory=AccountLimits)
    buffer_bars: int = 2000
```

Everything the portfolio orchestrator needs to emit one target.
`weights` are fractions (normalized to sum 1 at construction of the live
orchestrator); `vol_target` is an annualized fraction. Weights come from
the research-side refit and are static per run, refreshed offline between
sessions.

### `RiskConfig`

```python
@dataclass(frozen=True)
class RiskConfig:
    limits: AccountLimits = field(default_factory=AccountLimits)
    instrument: Instrument = field(default_factory=lambda: Instrument.load("VN30F1M"))
    intraday_loss_limit: float = 0.02
    staleness_secs: float = 60.0
    session_close_local_time: str = "14:00"
    tz: str = "Asia/Ho_Chi_Minh"
    flatten_max_attempts: int = 3
    flatten_retry_secs: float = 1.0
```

Everything the risk overlay needs to approve one target.
`intraday_loss_limit` is a fraction of `limits.capital_vnd`
(`0.02` == 2%).

### `TargetPosition`

```python
@dataclass(frozen=True)
class TargetPosition:
    ts: datetime
    target_contracts: int
    z_target: float
    reason: str
    components: dict[str, float] = field(default_factory=dict)
```

The portfolio's desired signed position for one decision timestamp. A
request — not a risk approval, actual position, Nautilus order, or fill.

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `ts` | datetime | tz-aware | Decision timestamp. |
| `target_contracts` | int | contracts | Signed; 0 = flat. |
| `z_target` | float | z-units | Pre-rounding z-scale target (debug/telemetry). |
| `reason` | str | — | Non-empty; live values: `warmup`, `invalid-input`, `cap-limited`, `flat-no-signal`, `signal`. |
| `components` | dict[str, float] | z-units | Per-expression telemetry. |

Raises (`__post_init__`): `ValueError` — tz-naive `ts`, non-int
`target_contracts`, non-finite `z_target`, empty `reason`, or a
`components` dict with empty names / non-finite values.

### `Portfolio` (protocol)

```python
class Portfolio(Protocol):
    def compute_target(self, bars: dict[str, list[float]], ts: datetime) -> TargetPosition: ...
```

Orchestration side: bars in (`"close"`/`"volume"` lists), one target out.
Pure alpha_core calls. Implemented by `trading.portfolio.PortfolioOrchestrator`.

### `RiskState`

```python
@dataclass(frozen=True)
class RiskState:
    status: str = "ACTIVE"
    reason: str = ""
```

Risk status: `ACTIVE` | `HALTED` (soft halt) | `REDUCING`.

### `RiskController` (protocol)

```python
class RiskController(Protocol):
    def decide(self, target: TargetPosition) -> "RiskDecision": ...
```

Risk side: decide how a desired target may proceed.

### `RiskDecision`

```python
RiskAction = Literal["approve", "cap", "block", "force-flat"]

@dataclass(frozen=True)
class RiskDecision:
    desired: TargetPosition
    approved_target_contracts: int
    action: RiskAction
    reason: str
    current_contracts: int
```

Risk's decision for one portfolio desired target. `approved_target_contracts`
is what execution may pursue; `current_contracts` is the actual signed
position observed by the risk layer. A blocked decision retains that actual
position as its approved target; a force-flat decision always approves zero.

Raises (`__post_init__`): `ValueError` — non-int contract fields, unknown
`action`, empty `reason`, `approve` not preserving the desired target, `cap`
not changing / increasing / reversing the desired target, `force-flat`
approving non-zero, or `block` not retaining the current position.

---

## Score -> contracts mapping (`core.mapping`)

One formula, one module. `L_max = floor(capital_vnd * safety_factor /
(margin_rate * price * multiplier))`; `raw = round(z / cap * L_max)`
(half-to-even), clipped to `+/-max_contracts`.

### `max_contracts_at`

```python
def max_contracts_at(price: float, instrument: Instrument, limits: AccountLimits) -> int
```

Margin-feasible maximum signed-contract magnitude at a price.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `price` | float | VND per index point | Reference price (e.g. last close). |
| `instrument` | Instrument | — | Supplies `multiplier`. |
| `limits` | AccountLimits | — | Supplies `capital_vnd`, `safety_factor`, `margin_rate`. |

Returns: int — the floor above; NOT clamped by `max_contracts` (callers
clip).

### `to_contracts`

```python
def to_contracts(z: float, price: float, cap: float, instrument: Instrument, limits: AccountLimits) -> int
```

One z-score target -> signed contract count (the live path, stateless).

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `z` | float | z-units | Composite score target. |
| `price` | float | VND per index point | Reference price. |
| `cap` | float | z-units | z-value mapped to the maximum position; must be positive. |
| `instrument` | Instrument | — | Multiplier. |
| `limits` | AccountLimits | — | Sizing inputs + hard `max_contracts` clip. |

Returns: int — `round(z / cap * max_contracts_at(...))` clipped to
`+/-limits.max_contracts`; 0 for non-finite `z` or non-finite/non-positive
`price`.

### `hysteresis_band_contracts`

```python
def hysteresis_band_contracts(band: float, cap: float, price: float, instrument: Instrument, limits: AccountLimits) -> int
```

No-trade band width in z-units -> contract-count band.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `band` | float | z-units | Band width (e.g. `HarnessParams.band`). |
| `cap` | float | z-units | z mapped to the maximum position; must be positive. |
| `price`, `instrument`, `limits` | — | — | Sizing inputs (see `max_contracts_at`). |

Returns: int — `max(1, round(band / cap * max_contracts_at(...)))` (at
least one contract, so a flat book can always react).

### `apply_hysteresis`

```python
def apply_hysteresis(raw: int, prev: int, band_contracts: int) -> int
```

Hold the previous position while the change stays inside the band. Returns
`prev` when `abs(raw - prev) <= band_contracts`, else `raw`. Research
backtest loops call this between rounds; live callers never do.

---

## Expiry rule (`core.expiry`)

Locked behavior: [../conventions.md](../conventions.md#expiry-rule).

### `ExpiryState`

```python
@dataclass(frozen=True)
class ExpiryState:
    blocked_session_date: date | None = None
    last_processed_expiry_date: date | None = None
```

Position-level state for expiry close and same-session re-entry. Carried
from decision to decision.

### `ExpiryGateDecision`

```python
@dataclass(frozen=True)
class ExpiryGateDecision:
    approved_target_contracts: int
    force_flat: bool
    reentry_blocked: bool
    reason: str
    state: ExpiryState
```

Outcome for one target position. `reason` is `""`,
`"expiry-reduce-only"`, `"expiry-force-close"` or
`"expiry-reentry-blocked"`.

### `apply_expiry_gate`

```python
def apply_expiry_gate(
    ts_utc: pd.Timestamp,
    target_contracts: int,
    current_contracts: int,
    state: ExpiryState,
    *,
    enabled: bool,
    close_time_local: str = "14:00",
    tz: str = "Asia/Ho_Chi_Minh",
    working_dates: tuple[str, ...] = (),
) -> ExpiryGateDecision
```

Apply the expiry rule to one TARGET position at one timestamp.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `ts_utc` | pandas.Timestamp | UTC | Decision timestamp. |
| `target_contracts` | int | contracts | Desired signed target from the portfolio layer. |
| `current_contracts` | int | contracts | Actual signed position at `ts_utc`. |
| `state` | ExpiryState | — | State from the previous decision. |
| `enabled` | bool (keyword-only) | — | Master switch; `False` approves unchanged, state untouched. |
| `close_time_local` | str | local `HH:MM` | Expiry-day cutoff (default `"14:00"`). |
| `tz` | str | — | IANA zone for the session date. |
| `working_dates` | tuple[str, ...] | ISO date strings | Market working dates; expiry = latest available on/before the third Thursday. |

Returns: `ExpiryGateDecision`. Raises: `TypeError` — tz-naive `ts_utc`;
`ValueError` — `close_time_local` not `"HH:MM"`.

### `vn30_front_month_expiry_cutoff_utc`

```python
def vn30_front_month_expiry_cutoff_utc(ts_utc: pd.Timestamp, working_dates: tuple[str, ...] = ()) -> pd.Timestamp
```

Expiry-day cutoff (local close) as UTC. `ts_utc` may be any timestamp
inside the target month. Raises: `TypeError` — tz-naive input.

### `vn30_front_month_expiry_date_local`

```python
def vn30_front_month_expiry_date_local(ts_utc: pd.Timestamp, working_dates: tuple[str, ...] = ()) -> date
```

Front-month expiry trading date in local time: the month's third Thursday,
walked back to the latest available working date when a calendar is given.
Raises: `TypeError` — tz-naive input.

---

## Artifacts (`core.artifacts`)

Only cross-role artifacts are auto-saved (trial ledger, pool, weights);
reports are in-memory with explicit `to_json`/`save`.

### `Window`

```python
@dataclass(frozen=True)
class Window:
    instrument_id: str
    bar_type: str
    start: pd.Timestamp
    end: pd.Timestamp
    n_bars: int
```

The exact data window an artifact was computed over (`start`/`end` UTC, end
inclusive).

### `PoolSchemaError`, `WindowMismatch`

```python
class PoolSchemaError(ValueError)   # pool file schema_version != "2"
class WindowMismatch(ValueError)    # artifact Window does not match the data it is applied to
```

### `TearSheet`

```python
@dataclass(frozen=True)
class TearSheet:
    alpha_id: str
    dsl: str
    metrics: dict
    verdict: str              # "IN" | "OUT"
    reasons: tuple[str, ...] = ()
    provenance: dict = field(default_factory=dict)
    generated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict
    @classmethod
    def from_dict(cls, d: dict) -> "TearSheet"
    def to_json(self, path: str | Path) -> Path
```

Evaluation report for one alpha. `metrics` keys: `net_sharpe`,
`max_drawdown`, `cost_drag_pct` (percent), `total_net_pnl`, `ic_ladder`
(list of `{horizon, mean_ic, t_stat}`), `best_horizon`, `best_abs_ic`,
`icir` (float | None), `walk_forward` (`{positive_pct, worst_block_sharpe,
n_blocks}`), `hints` (list[str]). `provenance` carries engine version,
harness, gate, window.

### `SpecSheet`

```python
@dataclass(frozen=True)
class SpecSheet:
    alpha_id: str
    expected_holding_period_bars: int
    expected_net_sharpe: float
    capacity_contracts: int
    regime_notes: str = ""
    kill_criteria: dict = field(default_factory=dict)
    expected_ic: dict[str, float] = field(default_factory=dict)
    cost_model_bps: float = 2.294

    def to_dict(self) -> dict
    @classmethod
    def from_dict(cls, d: dict) -> "SpecSheet"
```

Component-2 PASS artifact: expectations consumed by portfolio (capacity,
expected Sharpe, holding period), risk (divergence gauges, expected IC, cost
model in bp) and the live kill criteria.

### `PoolEntry`

```python
@dataclass
class PoolEntry:
    alpha_id: str
    dsl: str
    author: str = "research"
    tags: tuple[str, ...] = ()
    family: str | None = None
    source: str = "seed"          # "seed" (hand-written) | "ga" (bred)
    created: str = field(default_factory=lambda: date.today().isoformat())
    schema_version: str = POOL_SCHEMA_VERSION
    tear_sheet: TearSheet | None = None
    spec_sheet: SpecSheet | None = None

    def to_dict(self) -> dict
    @classmethod
    def from_dict(cls, d: dict) -> "PoolEntry"
```

One passing alpha in the pool folder; JSON round-trippable. `dsl` is the
canonical DSL string (`validate_expression_py` round-trip).

### `AlphaPool`

```python
@dataclass
class AlphaPool:
    instrument: str
    entries: list[PoolEntry] = field(default_factory=list)

    def add(self, entry: PoolEntry) -> None
    def save(self, root: Path | None = None) -> Path
    @classmethod
    def load(cls, root: Path | None = None) -> "AlphaPool"
```

The research -> portfolio handoff pool (folder-backed). Layout:
`alphas/<alpha_id>.json` per entry plus `index.json`; the folder is the
single source of truth.

- `add` — append in memory; `save` persists.
- `save(root=None)` — writes the folder (default `DEFAULT_POOL_DIR`);
  returns the pool folder written.
- `load(root=None)` — reads every alpha file sorted by `alpha_id`;
  `instrument` comes from `index.json` when present, else `""`.
  Raises: `PoolSchemaError` — foreign `schema_version` (message instructs
  re-delivery); `ValueError` — unreadable JSON.

### `Composite`

```python
@dataclass(frozen=True)
class Composite:
    alpha_ids: tuple[str, ...]
    weights: tuple[float, ...]
    scores: np.ndarray          # z-units
    window: Window
    method: str
```

One composite score series plus full construction provenance. `weights`
are fractions aligned with the sorted `alpha_ids`. Raises (`__post_init__`):
`ValueError` — `alpha_ids`/`weights` length mismatch or non-finite
`scores`.

### `TargetSeries`

```python
@dataclass(frozen=True)
class TargetSeries:
    ts: pd.DatetimeIndex        # UTC, sorted
    target_contracts: np.ndarray  # int
    window: Window
    instrument: Instrument

    def to_frame(self) -> pd.DataFrame
    @classmethod
    def from_arrays(cls, ts: pd.DatetimeIndex, target_contracts: np.ndarray, window: Window, instrument: Instrument) -> "TargetSeries"
```

A signed target-contract series over one data window. `to_frame` returns
columns `ts`, `target_contracts` (int64). `from_arrays` validates: raises
`ValueError` for tz-naive/unsorted `ts` or length mismatch with
`target_contracts`; naive arrays are cast to int64.

### `WeightsArtifact`

```python
@dataclass(frozen=True)
class WeightsArtifact:
    generated: str
    method: str
    weights: dict[str, float]
    window: Window | None

    def save(self, root: Path | None = None) -> Path
    @classmethod
    def load(cls, root: Path | None = None) -> "WeightsArtifact"
```

Refit weights handed from research to the live portfolio config.
`weights` are keyed by `alpha_id` (fractions); the live runner joins them
to DSL through `AlphaPool.load()`. `save`/`load` read/write
`<root>/weights.json` (default root `DEFAULT_POOL_DIR`). Raises (`load`):
`FileNotFoundError` — no `weights.json` under `root`.

### `append_trial_ledger`

```python
def append_trial_ledger(entry: dict, root: Path | None = None) -> Path
```

Append one trial record as a JSONL line (append-only) to
`<root>/trial_ledger.jsonl` (default `DEFAULT_RESEARCH_DIR`). Consumers:
deflated-threshold trial count, mining family priors, post-mortem. The
entry should carry at least `alpha_id`, `dsl`, `date`, `verdict`, a metrics
summary and provenance. Returns the ledger path.

---

## Registries (`core.registry`)

### `Method`

```python
@dataclass(frozen=True)
class Method:
    name: str
    fn: object
    source: str                # "engine" (Rust-backed default) | "python" (research)
    description: str = ""
    capability: str | None = None
```

### `Registry`

```python
class Registry:
    def __init__(self, slot: str, *, contract: type | None = None, capability: str | None = None, adapter: Callable[[Callable[..., Any]], object] | None = None) -> None
    def register(self, name: str, fn: T, *, source: str = "python", description: str = "", replace: bool = False) -> T
    def get(self, name: str) -> Method
    def call(self, name: str, *args: Any, **kwargs: Any) -> Any
    def names(self) -> list[str]
    def describe(self) -> list[dict[str, str]]
```

Name -> `Method` store with strict duplicate handling.

- `register` — validates the name, the source (`"engine"` | `"python"`),
  contract/capability conformance, and rejects duplicate names unless
  `replace=True`. Returns `fn` unchanged.
- `get` — raises `KeyError` naming the slot and the registered names.
- `call` — dispatch through the capability attribute when set, else call
  `fn`; raises `TypeError` when the stored method is not callable.
- `describe` — `[{"name", "source", "description"}, ...]`.

The module slots and their built-ins are listed in
[../conventions.md](../conventions.md#extension-registries).
