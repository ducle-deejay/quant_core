# Reference: risk

`quantcore.risk` — the Quant Risk Researcher module. Owns the sizing model
(vol-target stack + leverage cap + drawdown overlay -> target position) and
the risk-overlay policies. The core entry point is `backtest_portfolio`: a
position-level portfolio backtest measuring performance before and after
exposure adjustment, always paired with risk-process metrics (overfit
guard). z-scores are z-units; positions are integer contracts (`_contracts`);
money carries `_vnd`; `vol_target` and loss limits are fractions;
`*_pct` outputs are percent.

## `backtest_portfolio`

```python
def backtest_portfolio(composite: Composite, bars: BarFrame, config: RiskBacktestConfig | None = None) -> RiskBacktestResult
```

PORTFOLIO BACKTEST (position level): sizing -> policy -> PnL, run "before"
(sizing only) and "after" (policy applied). Sizing and policy are resolved
through the `sizing_methods` / `risk_policies` registries (real dispatch;
defaults `vol_target_drawdown` / `trigger_matrix` — `RiskBacktestConfig`
carries no method names, so selection happens at the registry). The
contract conversion goes through `core.mapping` (band hysteresis in
contract units; the band applies to the UNCLIPPED raw count and the clip to
`+/-max_contracts` happens only when the position actually moves). The
drawdown proxy and intervention-cost math use the bar instrument's
multiplier.

| Parameter | Type | Unit | Meaning |
|---|---|---|---|
| `composite` | Composite | z-units | Combined composite; its `window` must equal `bars.window`. |
| `bars` | BarFrame | — | Bar window (close feeds returns and marks). |
| `config` | RiskBacktestConfig \| None | — | Defaults to `RiskBacktestConfig()`. |

Returns: `RiskBacktestResult`. Raises: `WindowMismatch` —
`composite.window != bars.window`; `ValueError` — composite length
mismatch, unknown sizing/policy names, or a sizing method returning
malformed values.

## `RiskBacktestConfig`

```python
@dataclass(frozen=True)
class RiskBacktestConfig(
    harness: HarnessParams = field(default_factory=HarnessParams),
    vol_target: float = 0.1,
    vol_floor: float | None = None,
    risk: RiskConfig = field(default_factory=RiskConfig),
    limits: AccountLimits = field(default_factory=AccountLimits),
) -> None
```

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `harness` | HarnessParams | — | band/cap feed the hysteresis; `bars_per_day` the PnL aggregation. |
| `vol_target` | float | annualized fraction | Vol target for the sizing stack. |
| `vol_floor` | float \| None | annualized fraction | Optional vol floor. |
| `risk` | RiskConfig | — | Live-equivalent risk configuration; the offline ledger is constructed from it. |
| `limits` | AccountLimits | — | Capital, safety factor, margin rate, `max_contracts` for the conversion. |

## `SideReport`, `RiskBacktestResult`

```python
@dataclass(frozen=True)
class SideReport(performance: dict, risk_process: dict) -> None
```

| Field | Type | Meaning |
|---|---|---|
| `performance` | dict | `net_sharpe`, `max_drawdown`, `total_net_pnl` of the side's contract series (canonical PnL units; Sharpe/drawdown scale-free). |
| `risk_process` | dict | `n_interventions`, `intervention_cost_estimate_vnd` (cost of trading the "after" series itself: sum of |fill deltas| priced at `cost_per_side` x price x multiplier), `mean_abs_tracking_error` (mean |after - before|, contracts), `max_abs_position` (contracts), `trigger_counts` (every policy reason: status changes AND gate denials). |

```python
@dataclass(frozen=True)
class RiskBacktestResult(
    targets: TargetSeries,
    before: SideReport,
    after: SideReport,
    interventions: list[dict],
    metrics_diff: dict,
    provenance: dict,
) -> None
```

| Field | Type | Meaning |
|---|---|---|
| `targets` | TargetSeries | The "after" contract series — the artifact handed to execution. |
| `before` / `after` | SideReport | Sizing-only / policy-applied sides. |
| `interventions` | list[dict] | Status-change events: `{"ts", "previous", "current", "reason"}`. |
| `metrics_diff` | dict | `after.performance - before.performance` for `net_sharpe` and `max_drawdown`. |
| `provenance` | dict | Sizing/policy names + registry sources + engine version. |

In-memory, never auto-saved.

## Sizing registry

```python
sizing_methods = Registry("sizing_methods")
```

Uniform call convention for every method (engine defaults and
python-registered alike):
`fn(z_scores, vol_est, target_vol, drawdowns=None, floor=None) ->
list[float]`. Built-ins (`source="engine"`): `vol_target`
(`alpha_core.vol_target_py`), `drawdown_overlay` (no-op when `drawdowns`
is None), `vol_target_drawdown` (the wired default: vol target, then
drawdown multiplier). The rolling realized-vol estimate fed as `vol_est`
uses `VOL_EST_WINDOW = 20` bars (ddof=1, `sqrt(bars_per_day)` annualized).

## `PolicyInput`, risk-policy registry

```python
@dataclass(frozen=True)
class PolicyInput(ts: datetime, position: int, session_pnl: float, target: int, config: dict, ledger: object, price: float) -> None
```

One risk-policy decision request — the FULL custom-policy contract.

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `ts` | datetime | UTC preferred | Bar/decision timestamp. |
| `position` | int | contracts | Current signed position. |
| `session_pnl` | float | VND | Session PnL so far (realized + marked). |
| `target` | int | contracts | Desired signed position. |
| `config` | dict | — | `RiskConfig` asdict. |
| `ledger` | object | — | The loop's ledger (`RiskLedger`; used by `trigger_matrix` only). |
| `price` | float | VND per index point | Current price (bar close); mark and fill price. |

```python
risk_policies = Registry("risk_policies")
```

Custom policy contract: `fn(policy_input: PolicyInput) -> dict` with keys
`{"status", "allowed_position", "reason"}`. Built-in `"trigger_matrix"`
(source `"python"`): drives the `RiskLedger` per bar (fills for position
deltas, mark at close, bar arrival, `decide()`), then applies gate
semantics — HALTED flattens, REDUCING only reduces, ACTIVE allows targets
within `max_contracts` — and records fills for the allowed deltas.

## `RiskLedger`

```python
@dataclass
class RiskLedger:
    config: RiskConfig
    status: str = "ACTIVE"
    reason: str = ""
    realized_pnl_vnd: float = 0.0
    marked_pnl_vnd: float = 0.0
    last_bar_ts: datetime | None = None
    last_bar_seen_session: bool = False
    intraday_start_ts: datetime | None = None

    def record_fill(self, price: float, qty: int, ts: datetime) -> None
    def mark(self, price: float, ts: datetime) -> None
    def on_bar(self, ts: datetime) -> None
    def reconcile_position(self, contracts: int, avg_entry: float | None = None) -> None
    def decide(self)
    def gate(self, target_contracts: int, current_contracts: int) -> tuple[bool, str]
```

Offline Component-7 risk ledger: the trigger-matrix state machine (port of
the live ledger, rewired to `core.contracts.RiskConfig`). Derived state
(not constructor arguments): `position` (signed contracts from fills),
`avg_entry`, `last_price`, `_now_ts`.

Trigger matrix (priority order, first match wins):

| Priority | Condition | Status | Reason |
|---|---|---|---|
| 1 | realized + marked <= -intraday_loss_limit x capital | HALTED | `intraday-loss-limit` |
| 2 | no bar within `staleness_secs` while the session is open | HALTED | `stale-feed` |
| 3 | abs(position) > max_contracts | REDUCING | `exposure-cap` |
| 4 | otherwise | ACTIVE | `""` |

Day rollover: the intraday loss limit is per trading session day — on the
first event of a new local session day the PnL counters reset and a loss
halt lifts. Positions carry across days. Only `decide()` mutates
status/reason.

| Method | Meaning |
|---|---|
| `record_fill(price, qty, ts)` | Accumulate one signed fill (`qty > 0` buys); realized PnL `closed_qty * (price - avg_entry) * multiplier` on reducing/flipping fills; extensions re-weight the average entry. |
| `mark(price, ts)` | Mark to market at `price` (last close). |
| `on_bar(ts)` | Record a bar arrival; drives staleness and rollover. |
| `reconcile_position(contracts, avg_entry=None)` | Seed from an external position view; does not touch intraday PnL. |
| `decide()` | Evaluate the trigger matrix, mutate status, return `RiskState`. Staleness needs a time reference, an in-session last bar and an open session; before any event the ledger returns ACTIVE. Staleness cannot fire on a continuous bar feed. |
| `gate(target_contracts, current_contracts)` | HALTED denies everything (reason `halted:<reason>`); REDUCING allows only strictly |reducing| moves; ACTIVE allows `abs(target) <= max_contracts`, else denies `exceeds-max-contracts`. Returns `(allowed, reason)`. |

### Session helpers (module-level)

```python
def parse_close_time(value: str) -> time
def in_tz(ts: datetime, tz: str) -> datetime
def is_session_open(ts: datetime, session_close_local_time: str, tz: str) -> bool
def session_day(ts: datetime, tz: str) -> date
```

`parse_close_time` parses `"HH:MM"` (raises `ValueError` otherwise);
`in_tz` projects a timestamp (naive input interpreted in `tz`);
`is_session_open` is True before the configured local close (the session
runs from local midnight up to, not including, close time; overnight
sessions are out of scope); `session_day` is the local calendar date used
as the rollover key.

## `divergence_gauges`

```python
@dataclass(frozen=True)
class GaugeReport(gauges: dict, escalation: str) -> None
```

| Field | Type | Meaning |
|---|---|---|
| `gauges` | dict | Gauge id -> `{"value", "expected", "status", "note"}` (value may be None with status `"n/a"` and a reason note). |
| `escalation` | str | `"critical"` / `"warning"` / `"none"` across all gauges. |

```python
def divergence_gauges(spec: SpecSheet, live: dict) -> GaugeReport
```

Divergence gauges comparing live behavior against the spec sheet. Each
gauge is computed only from the inputs present; missing inputs yield value
None with a reason.

| Parameter | Type | Meaning |
|---|---|---|
| `spec` | SpecSheet | Expectations (`expected_ic`, `cost_model_bps`). |
| `live` | dict | Optional keys: `score`, `returns`, `fills` (each fill with `price`/`decision_mid`/`side`), `current_positions`, `target_positions`, `orders`, `n_fills`, `feed_gaps`. |

Gauges: (1) rolling PREDICTIVE IC vs `spec.expected_ic` — standard-error
bands (warning |v-e| > 2.5 se, critical > 4 se, se = 1/sqrt(n)); horizon =
the ladder entry with max |expected IC|; the spec IC is score_t vs forward
returns, so a contemporaneous correlation would false-critical healthy
signals. (2) implementation shortfall vs `spec.cost_model_bps` (ratio
bands: ok <= 0.5, warning <= 1.0 of the distance). (3) position tracking
error vs `TRACKING_ERROR_BOUND_CONTRACTS = 1.0` (UPPER limit; warning at
2x). (4) fill rate vs `FILL_RATE_EXPECTED = 0.95` (LOWER limit; 0 fills or
below half the expected rate is critical).

## `post_mortem`

```python
@dataclass(frozen=True)
class SessionReport(
    session_dir: str,
    n_decision_events: int,
    n_risk_transitions: int,
    timeline: list[dict],
    target_flips: int,
    big_gap_moves: int,
    risk_transition_counts: dict,
    recommendations: list[dict],
) -> None
```

| Field | Type | Meaning |
|---|---|---|
| `session_dir` | str | Dissected session directory. |
| `n_decision_events` / `n_risk_transitions` | int | Event counts from both logs. |
| `timeline` | list[dict] | First 200 events merged from both logs (sorted by `ts_ns`/`ts`); each `{"ts_ns", "kind", "fields"}`. |
| `target_flips` | int | Target changes in the decision log. |
| `big_gap_moves` | int | Target changes of 3+ contracts. |
| `risk_transition_counts` | dict | `"status:reason"` -> count. |
| `recommendations` | list[dict] | Candidate recommendations derived from the triggers observed. |

```python
def post_mortem(session_dir: Path) -> SessionReport
```

Session dissection: reads `decisions.jsonl` and `risk_transitions.jsonl`
under `session_dir` and returns the structured timeline and candidate
recommendations (data only — never auto-applied). Unparseable lines are
skipped.
