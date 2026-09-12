# Conventions

Shared rules every module, artifact and config follows. Each quickstart and
reference page links here instead of restating them.

## Units

One unit per concept; the name carries the suffix, the value carries no
ambiguity.

| Quantity | Unit | Naming rule | Example |
|---|---|---|---|
| Alpha scores, composite values, z-targets | z-units (dimensionless, standardized) | fields/params named `scores`, `z`, `z_target` — never bare `position` for z-values | `Composite.scores`, `TargetPosition.z_target`, `to_contracts(z=...)` |
| Position sizes, order quantities, gaps | integer contracts | names end in `_contracts` | `target_contracts`, `gap_contracts`, `capacity_contracts` |
| Money | VND | names end in `_vnd` | `capital_vnd`, `realized_pnl_vnd`, `intervention_cost_estimate_vnd` |
| Ratios, fractions, probabilities | fraction (default) | no suffix; `0.02` == 2% | `intraday_loss_limit=0.02`, `vol_target=0.1`, `safety_factor=0.5`, `margin_rate=0.05` |
| Percent values | percent | names end in `_pct`; `40.0` == 40% | `max_cost_drag_pct=40.0`, `cost_drag_pct`, `positive_pct` |
| Costs, slippage, shortfall | basis points of the reference price | names end in `_bps` or `bp` | `cost_model_bps=2.294`, `slippage_bps_mean`; 2.294 bp == 0.000229 as a fraction |
| Prices, index points | VND per index point | plain floats | `Instrument.multiplier=100_000.0` (VND per index point), `tick_size=0.1` |
| Timestamps | UTC (pandas/DatetimeIndex or tz-aware datetime); session logic projects to `Asia/Ho_Chi_Minh` | `ts`, `ts_utc` | `BarFrame.ts`, `apply_expiry_gate(ts_utc=...)` |
| Research PnL metrics | canonical composite units (position x return per bar) — NOT capital fractions; Sharpe/IC/drawdown are scale-free | reported in `PortfolioHealth.units` | `SideReport.performance` |

Contract conversion (the one formula, `core.mapping`):

```
L_max     = floor(capital_vnd * safety_factor / (margin_rate * price * multiplier))
contracts = round(z / cap * L_max)          # Python round: half-to-even
contracts = clip(contracts, -max_contracts, +max_contracts)
```

Research backtests add a no-trade band in contract units
(`hysteresis_band_contracts` + `apply_hysteresis`); the live path converts
statelessly with `to_contracts`.

## Artifact flow

Research (offline, this repo's `quantcore` package):

```
AlphaPool
   |  score_pool(pool, bars)
   v
{alpha_id: raw score rows}
   |  combine(scores, method, window)         refit_weights(pool, bars)
   v                                                  |
Composite --------------------------------------> WeightsArtifact (data/pool/weights.json)
   |
   |  health_report(composite, bars)  -> PortfolioHealth   (in memory)
   |  orthogonalize(candidate, scores) -> OrthoReport       (in memory)
   v
backtest_portfolio(composite, bars)
   |
   v
RiskBacktestResult.targets  (= TargetSeries)
   |
   v
backtest_execution(targets, bars [, catalog])
   |
   v
ExecutionReport  ->  slippage_report  (feedback execution -> alpha)
```

Live (the runner in `apps/trading/run.py`):

```
WeightsArtifact + AlphaPool
   |  portfolio_config_from_pool(artifact, pool, instrument, limits)
   |  weights are keyed by alpha_id; joined to DSL through AlphaPool.load()
   v
PortfolioConfig
   |  PortfolioOrchestrator.compute_target(bars, ts)
   v
TargetPosition (desired)
   |  RiskOverlayActor.decide(target)
   v
RiskDecision (approve | cap | block | force-flat)
   |
   v
BridgeStrategy -> orders
```

Live (the runner in `apps/trading/run.py`):

```
WeightsArtifact + AlphaPool
        |  weights keyed by alpha_id; joined to DSL through AlphaPool.load()
        v
portfolio_config_from_pool --> PortfolioConfig
        v
PortfolioOrchestrator.compute_target(bars, ts) --> TargetPosition (desired)
        v
RiskOverlayActor.decide --> RiskDecision (approve | cap | block | force-flat)
        v
BridgeStrategy --> orders
```

Auto-saved artifacts only: trial ledger (`data/research/trial_ledger.jsonl`),
pool (`data/pool/alphas/*.json` + `index.json`), weights
(`data/pool/weights.json`). Reports (`TearSheet`, `SpecSheet`,
`PortfolioHealth`, `SideReport`, `GaugeReport`, `ExecutionReport`,
`SlippageReport`) are in-memory; every `save()` call is explicit.

## Environments and accounts

Two independent axes:

| Axis | Values | Selected by | Meaning |
|---|---|---|---|
| Nautilus runtime context | `backtest` / `sandbox` / `live` | `runtime.json` key `environment` | `backtest`: offline engine (`quantcore.execution`, never the live runner — `build_node` raises `NotImplementedError`). `sandbox`: node composed against real DNSE data with locally simulated matching. `live`: full live node through the broker adapter. |
| Broker account boundary | `demo` / `live` | `runtime.json` key `account` | Which entrade account the execution client logs into. `demo` = broker demo account. `live` = real-money account; a config file alone can never select it — the operator must also pass `--confirm-live-account` on the runner CLI. |

The four combinations are all expressible; the shipped default is
`environment="live"` + `account="demo"`.

## runtime.json key reference

Path: `apps/trading/config/runtime.json` (override with
`apps/trading/run.py --config PATH`). Loading is strict: unknown keys raise
`ValueError`; missing keys take the documented defaults.

| Key | Type | Default | Effect |
|---|---|---|---|
| `instrument` | string | `"VN30F1M"` | Symbol resolved through `core.Instrument.load` (definition JSON in `src/market_data/instrument_definitions/`). Unknown symbols fail at config load. |
| `capital_vnd` | number | `100000000.0` | Account capital in VND; becomes `AccountLimits.capital_vnd` (contract sizing). Must be positive and finite. |
| `environment` | string | `"live"` | Nautilus runtime context: `"sandbox"` or `"live"` (the runner composes live runtimes only); `"backtest"` is accepted by the loader and rejected by `build_node`. |
| `broker` | string | `"entrade"` | Broker adapter registry key (`trading.node`). |
| `account` | string | `"demo"` | Broker account boundary `"demo"` or `"live"`. `"live"` additionally requires `--confirm-live-account`. |
| `close_positions_on_expiry_day` | boolean | `true` | Master switch for the expiry gate (force-flat at the expiry cutoff, reduce-only before it). The single operator-facing expiry knob. |

CLI flags of `apps/trading/run.py`: `--config PATH`, `--confirm-live-account`.

Credentials come from the process environment (or `<repo>/.env`, loaded by
`trading.credentials`): `API_KEY`, `API_SECRET`, `ENTRADE_USERNAME`,
`ENTRADE_PASSWORD`, optional `ENTRADE_INVESTOR_ID`;
`TRADING_TELEGRAM_BOT_TOKEN` / `TRADING_TELEGRAM_CHAT_ID` for alerts.

## Expiry rule

Locked behavior for the VN30F1M front-month contract on its expiry trading
day. Implementation: `core.expiry.apply_expiry_gate`; operator switch:
`close_positions_on_expiry_day` in `runtime.json` (one flag — there are no
other runtime knobs).

- **Expiry date**: the month's third Thursday (of the decision timestamp's
  month, in `Asia/Ho_Chi_Minh`). With a market working-date calendar, the
  latest available working date on/before that Thursday is used; without
  one, the raw third Thursday.
- **Cutoff**: 14:00 local (`EXPIRY_HOUR_LOCAL`/`EXPIRY_MINUTE_LOCAL`,
  parameter default `close_time_local="14:00"`).
- **Before the cutoff, expiry day**: reduce-only — a desired target is
  approved only when it does not increase absolute exposure vs the current
  position (`abs(target) <= abs(current)`); otherwise the current position
  is held. Reason: `expiry-reduce-only`.
- **At/after the cutoff, first decision of the day**: approve 0 contracts,
  `force_flat=True`. Reason: `expiry-force-close`. The decision records both
  the session date and the processed expiry date in `ExpiryState`, making
  the step idempotent within the day.
- **Same session after the force**: approve 0, `reentry_blocked=True`.
  Reason: `expiry-reentry-blocked`.
- **Next session**: the block clears automatically when the local session
  date moves past `blocked_session_date`.
- **Flag off** (`enabled=False`): every target passes unchanged, state
  untouched.

Reason vocabulary: `""` | `expiry-reduce-only` | `expiry-force-close` |
`expiry-reentry-blocked`.

## Data access

- Research catalog: Nautilus parquet, default root
  `/Users/ducle/repos/nox_system/data/catalog` (override with the
  `QUANTCORE_CATALOG` environment variable). Default bar type
  `VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL`, instrument id `VN30F1M.HNX`.
- Bars are decoded only through `core.data.CatalogClient`
  (`ParquetDataCatalog`) — never `pd.read_parquet` directly, which returns
  bytes for the Nautilus-encoded price columns.
- Trade ticks and 10-level order-book depth exist under the raw
  continuous-contract id `41I1G9000.HNX` (same multiplier 100,000 VND per
  index point and tick size 0.1 as VN30F1M). Pass
  `Instrument(symbol="41I1G9000", venue="HNX", multiplier=100_000.0, tick_size=0.1)`
  to `backtest_execution` for tick mode.
- Dev-loop fixtures (real data excerpts committed under `tmp/fixtures/`):
  `bars_20260601_20260911.parquet` (the full catalog window 2026-06-01 to
  2026-09-11, 17,352 bars — identical to
  `CatalogClient().bars(DataConfig(start="2026-06-01", end="2026-09-12"))`)
  and `ticks_41I1G9000_20260821.parquet` (one trading day of trade ticks).
  Build a `BarFrame` from the bars fixture with
  `BarFrame.from_dataframe(df, instrument_id="VN30F1M.HNX",
  bar_type="VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL")`. Tick fixtures are for
  direct frame analysis; `backtest_execution` tick mode reads the catalog.

## Extension registries

Every extension slot is a `core.registry.Registry`; registry dispatch is the
real path — replacing a registration changes the calling function's output.

| Registry | Module | Built-ins (source) | Custom contract |
|---|---|---|---|
| `ga_fitness` | `quantcore.alpha` | `engine` (Rust GA; fixed fitness mean score x next-bar return) | `fn(seeds, close, volume, population_size, generations, seed) -> list[str]` |
| `quantitative_models` | `quantcore.alpha` | `engine_close` (Rust evaluator on DSL `"close"`) | object with `score(close, volume) -> list[float]` |
| `combine_methods` | `quantcore.portfolio` | `equal_weight`, `inverse_vol` (engine-backed) | `fn(scores: dict[str, numpy.ndarray]) -> (composite, weights dict)` |
| `sizing_methods` | `quantcore.risk` | `vol_target`, `drawdown_overlay`, `vol_target_drawdown` (engine-backed; default `vol_target_drawdown`) | `fn(z_scores, vol_est, target_vol, drawdowns=None, floor=None) -> list[float]` |
| `risk_policies` | `quantcore.risk` | `trigger_matrix` (Python port of the live ledger; default) | `fn(PolicyInput) -> {"status", "allowed_position", "reason"}` |
| `execution_algorithms` | `quantcore.execution` | `marketable_limit` (default), `twap` | `fn(gap_contracts: int, config: ExecutionConfig) -> list[int]` (signed chunks, positive = buy) |

## Naming

One stable name per concept within a scope; collisions are qualified by
owner (e.g. `DEFAULT_RESEARCH_DIR` exists in both `core.artifacts` and
`quantcore.execution` — same `<repo>/data/research` target, different
modules). Where established vocabularies differ, the docs state the mapping:
the engine's `position` series is a z-units canonical position; contract
counts always carry `_contracts`.
