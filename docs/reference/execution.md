# Reference: execution

`quantcore.execution` — the Execution Researcher module. Offline execution
research on the Nautilus backtest engine: target-following backtests (bar
mode / tick mode), child-order planning, urgency math and the slippage
review. `nautilus_trader` is imported lazily inside function bodies —
importing this module never imports Nautilus. Quantities are integer
contracts; slippage/shortfall are basis points of the reference price;
money is VND.

No instrument ids are hardcoded: instrument, venue, multiplier and tick
size all derive from `targets.instrument` (a `core.contracts.Instrument`)
and the bar window's `bar_type`.

Module constants: `DEFAULT_RESEARCH_DIR = <repo>/data/research` (default
root for `SlippageReport.save`).

## `ExecutionConfig`

```python
@dataclass(frozen=True)
class ExecutionConfig(
    harness: HarnessParams = field(default_factory=HarnessParams),
    order_style: str = "LO",
    cooldown_secs: float = 5.0,
    min_gap_contracts: int = 1,
    slice_bars: int = 12,
    twap_interval_secs: float = 60.0,
    limits: AccountLimits = field(default_factory=AccountLimits),
    allow_l1: bool = False,
) -> None
```

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `harness` | HarnessParams | — | Carried for provenance. |
| `order_style` | str | — | `"LO"` (limit at the decision price) or `"MAK"` (market). |
| `cooldown_secs` | float | seconds | Minimum seconds between order submissions. |
| `min_gap_contracts` | int | contracts | Smaller gaps (absolute) are not traded. |
| `slice_bars` | int | bars | TWAP slice count in bar mode (bar-per-chunk cadence); in tick mode `twap_interval_secs` turns it into a time horizon. |
| `limits` | AccountLimits | — | Capital funds the sim venue balance; `max_contracts` clamps applied targets. |
| `allow_l1` | bool | — | Tick mode: False requires order-book depth10 (raises if missing); True explicitly runs tick-only L1 matching. |

## `backtest_execution`

```python
def backtest_execution(
    targets: TargetSeries,
    bars: BarFrame,
    config: ExecutionConfig | None = None,
    algo: str = "marketable_limit",
    catalog: CatalogClient | None = None,
) -> ExecutionReport
```

Offline execution backtest on the Nautilus engine (`BacktestEngine`,
logging suppressed to ERROR). Two data modes:

- bar mode (default): the continuous instrument driven by the EXPLICIT
  `bars` window (real recorded bars; no catalog access).
- tick mode (`catalog` given): driven by real trade ticks with order-book
  depth10 feeding, loaded from the catalog for `targets.window` (extended
  by -5/+10 minutes); fills match against the actual book (L2 when depth
  exists, else L1 with `allow_l1=True`).

The strategy mirrors the live bridge semantics: at most one working order
(a partial fill keeps the order working — the working guard clears only on
a terminal fill), min-gap and cooldown skips, target changes only. Decision
mid = the reference price (bar close / last trade tick). After the
contract's simulated expiration no further orders are submitted.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `targets` | TargetSeries | — | Target contract series (`ts` + `target_contracts`). |
| `bars` | BarFrame | — | Bar window (consumed in bar mode; provenance in tick mode). |
| `config` | ExecutionConfig \| None | — | Defaults to `ExecutionConfig()`. |
| `algo` | str | — | Registry key in `execution_algorithms`. |
| `catalog` | CatalogClient \| None | — | REQUIRED for tick mode; omitted -> bar mode. |

Returns: `ExecutionReport`. Raises: `ValueError` — empty targets, unknown
algorithm, `bar_type`/instrument mismatch, or (tick mode) no ticks/depth in
the window (depth missing is an explicit error, not a silent degradation).

## `ExecutionReport`

```python
@dataclass(frozen=True)
class ExecutionReport(
    n_target_changes: int,
    n_orders: int,
    n_fills: int,
    n_rejected: int,
    slippage_bps_mean: float,
    slippage_bps_median: float,
    fills: pd.DataFrame,
    stats: dict,
    algo: str,
    provenance: dict,
) -> None
```

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `n_target_changes` | int | — | Number of target timestamps in the input series (bars with a target evaluated — parity with the previous system), NOT the number of value diffs. |
| `n_orders` | int | — | Submitted order count. |
| `n_fills` | int | — | (Partial-)fill event count with positive quantity. |
| `n_rejected` | int | — | Rejected order count. |
| `slippage_bps_mean` / `slippage_bps_median` | float | bp of decision mid | Fill slippage `(price - decision_mid) * side * 10_000 / decision_mid`; 0.0 with no fills. |
| `fills` | pandas.DataFrame | — | Columns `ts_ns, side, price, qty, decision_mid, slippage_bps`. |
| `stats` | dict | — | Sim-account stats: `n_positions`, `realized_pnl_vnd`, `account_balance`, `total_pnl`; carries `"error"` when the analyzer step failed (best-effort, never silent). |
| `algo` | str | — | The resolved execution-algorithm registry key. |
| `provenance` | dict | — | `algo`, `algo_source`, `order_style`, `engine`, `data_mode` (`"bar"`, `"tick-l1"`, `"tick-l2"`), `instrument_id`, `window_start`, `window_end`, `bars`. |

In-memory, never auto-saved. With `order_style="LO"` the fill price equals
the decision price, so `slippage_bps` is 0.0 by construction; meaningful
slippage needs tick mode and/or `"MAK"`.

## `execution_algorithms`, `plan_orders`

```python
execution_algorithms = Registry("execution_algorithms")
```

Plan contract: `fn(gap_contracts: int, config: ExecutionConfig) ->
list[int]` — signed child-order quantities, positive = buy. Built-ins:
`marketable_limit` (default; one order now, mirroring the live bridge),
`twap` (even slices over `slice_bars` bars, remainder front-loaded).

```python
def plan_orders(gap_contracts: int, config: "ExecutionConfig", algo: str = "twap") -> list[int]
```

Plan and validate signed child quantities for one position gap.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `gap_contracts` | int | contracts | Signed position gap (target - current). |
| `config` | ExecutionConfig | — | Handed to the algorithm. |
| `algo` | str | — | Registry key (default `"twap"`). |

Returns: signed child quantities with sum == gap, same sign, no zeros.
Raises: `TypeError` — non-integer gap or wrong config type; `ValueError` —
unknown algorithm or a plan violating the contract (non-integer/zero
quantities, wrong sum, reversed direction).

## `UrgencyInputs`, `UrgencyReport`, `urgency_analysis`

```python
@dataclass(frozen=True, kw_only=True)
class UrgencyInputs(
    *,
    gap_contracts: int,
    half_spread_bps: float,
    impact_bps: float,
    alpha_decay_per_bar: float,
    value_of_1bp: float,
    hold_bars: float = 1.0,
) -> None

@dataclass(frozen=True)
class UrgencyReport(cost_of_waiting: float, cost_of_acting: float, verdict: str) -> None
```

| `UrgencyInputs` field | Type | Unit | Meaning |
|---|---|---|---|
| `gap_contracts` | int | contracts | Gap magnitude the costs are computed on (non-negative). |
| `half_spread_bps` | float | bp of price (>= 0) | Half the current spread. |
| `impact_bps` | float | bp of price (>= 0) | Expected market impact. |
| `alpha_decay_per_bar` | float | bp of price per bar (>= 0) | Alpha decay per bar waited. |
| `value_of_1bp` | float | account currency (>= 0) | Money value of 1 bp of price for the whole gap. |
| `hold_bars` | float | bars (> 0) | Expected holding horizon for the waiting cost. |

```python
def urgency_analysis(inputs: UrgencyInputs) -> UrgencyReport
```

Trade-scheduling urgency math: `cost_of_waiting = gap *
alpha_decay_per_bar * value_of_1bp * hold_bars`; `cost_of_acting = gap *
(half_spread_bps + impact_bps) * value_of_1bp`; verdict `"act-now"` when
waiting costs more than acting, else `"slice"`. Units must be consistent
across inputs. Raises: `ValueError` — any negative input or non-positive
`hold_bars`.

## `SlippageReport`, `slippage_report`

```python
@dataclass(frozen=True)
class SlippageReport(
    generated: str,
    n_records: int,
    mean_shortfall_bps: float,
    median_shortfall_bps: float,
    cost_model_bps: float,
    excess_bps: float,
    by_session_hour: dict,
    size_buckets: dict,
    vol_regime: dict,
) -> None

    def save(self, root: Path | None = None) -> Path
```

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `generated` | str | — | ISO date of the report (also the save file name suffix). |
| `n_records` | int | — | Usable fill records (price + decision_mid + side present). |
| `mean_shortfall_bps` / `median_shortfall_bps` | float | bp of decision mid | Shortfall = `(price - decision_mid) * side * 10_000 / mid`. |
| `cost_model_bps` | float | bp | The cost model the excess is measured against (scalar fraction x 10,000 = 2.294). |
| `excess_bps` | float | bp | `mean_shortfall_bps - cost_model_bps`. |
| `by_session_hour` | dict | bp | Mean shortfall per VN session hour (`"HH"` keys, Asia/Ho_Chi_Minh; naive strings read as local, int `ts_ns` as UTC). |
| `size_buckets` | dict | bp | `"small_<=3"` / `"large_>3"` contracts. |
| `vol_regime` | dict | bp | Mean shortfall per caller-provided `vol_regime` label. |

`save(root=None)` persists the summary to `<root>/slippage_<generated>.json`
(default `<repo>/data/research`) — the weekly handoff artifact for
cost-model recalibration; returns the written path.

```python
def slippage_report(fills: pd.DataFrame | None = None, session_dir: Path | None = None) -> SlippageReport
```

Weekly implementation-shortfall review (feedback execution -> alpha).

| Parameter | Type | Meaning |
|---|---|---|
| `fills` | pandas.DataFrame \| None | Fill records with `price`, `decision_mid`, `side` and optional `qty`, `vol_regime`, `ts`/`ts_ns` columns. |
| `session_dir` | Path \| None | Directory holding `fills.jsonl` first; a bridge-style `decisions.jsonl` alone raises an actionable error — the bridge logs decisions only, fill prices live in the streaming catalog. |

Saving is the caller's explicit `SlippageReport.save()`. Raises:
`ValueError` — no input given, an unusable session dir, or no usable fill
records; `FileNotFoundError` — session dir has neither file.
