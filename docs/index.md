# quant_core documentation

A systematic-trading framework for VN30F1M futures: research APIs over the
real Nautilus parquet catalog and one live runner path. The code is the
source of truth; these pages document it.

## Start here

1. [conventions.md](conventions.md) — units, artifact flow, environments
   and accounts, `runtime.json` keys, the expiry rule, data access,
   extension registries. Everything else links to it.
2. Pick your persona:

| Persona | Page | Canonical chain |
|---|---|---|
| Alpha Researcher | [quickstart-alpha.md](quickstart-alpha.md) | catalog bars -> `evaluate_seed` -> `screen_batch` -> `build_spec_sheet` -> `deliver` / `PoolEntry` -> `pool.save()` |
| Portfolio Researcher | [quickstart-portfolio.md](quickstart-portfolio.md) | `AlphaPool.load` -> `score_pool` -> `combine` -> `refit_weights` -> `health_report` |
| Risk Researcher | [quickstart-risk.md](quickstart-risk.md) | `Composite` -> `backtest_portfolio` -> `RiskBacktestResult.targets` |
| Execution Researcher | [quickstart-execution.md](quickstart-execution.md) | `TargetSeries` -> `backtest_execution` (bar + tick mode) -> `ExecutionReport`; `urgency_analysis` |
| Quantitative Developer | [quickstart-developer.md](quickstart-developer.md) | `load_runtime` -> `portfolio_config_from_pool` -> `build_node` -> launchd |

Every quickstart is ONE complete script, copy-paste-executable with
`.venv/bin/python` against the real catalog
(`QUANTCORE_CATALOG`, default `/Users/ducle/repos/nox_system/data/catalog`)
or the committed fixtures in `tmp/fixtures/`, with the expected output
shown. The quickstarts are sequential: alpha writes the pool portfolio
consumes; risk and execution continue the chain.

## Reference

- [reference/core.md](reference/core.md) — data access (`DataConfig`,
  `BarFrame`, `CatalogClient`), instruments (`Instrument`, `CostModel`),
  contracts (`PortfolioConfig`, `TargetPosition`, `RiskDecision`, ...),
  score->contracts mapping, expiry rule, artifacts (`AlphaPool`,
  `Composite`, `TargetSeries`, `WeightsArtifact`, ...), registries.
- [reference/alpha.md](reference/alpha.md) — `evaluate_seed`,
  `screen_batch`, `mine_seeds`, `build_spec_sheet`, `deliver`, gate
  criteria.
- [reference/portfolio.md](reference/portfolio.md) — `score_pool`,
  `combine`, `refit_weights`, `health_report`, `orthogonalize`.
- [reference/risk.md](reference/risk.md) — `backtest_portfolio`,
  `RiskLedger`, registries, `divergence_gauges`, `post_mortem`.
- [reference/execution.md](reference/execution.md) —
  `backtest_execution`, `plan_orders`, `urgency_analysis`,
  `slippage_report`.

The live runner surface (`trading.config_loader.load_runtime`,
`trading.portfolio.portfolio_config_from_pool`,
`trading.node.build_node`) is documented in
[quickstart-developer.md](quickstart-developer.md).

## Layout of the repo

- `src/core/` — bottom layer (contracts, data, mapping, expiry, artifacts,
  registries). Imports stdlib + pandas + numpy only; Nautilus is lazy.
- `src/alpha-core/`, `src/alpha_core/` — Rust engine + PyO3 bindings
  (scoring, canonical mapping, combination, metrics).
- `src/quantcore/` — research APIs (`alpha`, `portfolio`, `risk`,
  `execution`).
- `src/trading/`, `apps/trading/` — live runner (config loader,
  orchestrator, risk overlay, bridge strategy, `run.py`, `runtime.json`,
  launchd template).
- `tmp/fixtures/` — committed real-data excerpts for fast loops.
- `data/pool/`, `data/research/`, `data/live/`, `data/logs/` — artifacts
  and logs (created on demand).
