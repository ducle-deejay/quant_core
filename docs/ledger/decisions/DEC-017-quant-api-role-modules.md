---
doc_id: DEC-017
title: quant_api - role-scoped Python API for the four practitioner roles
type: decision
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [api, python, roles, registry, artifacts, notebook]
source: "owner discussion 2026-09-01: role-oriented Python API above the engine bindings; users are researchers working in notebooks, later agents; research-fast / deploy-Rust extension pattern"
design: []
code: [src/quant_api, src/alpha-core/src/python_bindings/mining.rs]
test: [src/quant_api/tests]
---

# DEC-017 - quant_api: role-scoped Python API

## 1. Decision

A new uv-workspace package `src/quant_api` provides the user-facing Python API for the four practitioner roles. One module per role, notebook-first, deterministic, agent-ready (plain dataclasses plus JSON/parquet file output):

- `quant_api.research` - Quantitative Researcher: seed -> single-alpha evaluation (canonical simulation + evaluation gates) -> GA breeding from passing seeds -> candidate evaluation -> deliver to pool.
- `quant_api.portfolio` - Portfolio Researcher: load pool, orthogonalization, combination (allocation algorithms), weekly weight refit, monthly portfolio health report. Position sizing is NOT in scope here.
- `quant_api.execution` - Execution Researcher: offline execution backtest wrapping the Nautilus `BacktestEngine`/`ExecAlgorithm`/`PortfolioAnalyzer`, urgency analysis, weekly slippage attribution report.
- `quant_api.risk` - Quant Risk Researcher: owns the sizing model (vol-target stack + leverage cap + drawdown overlay -> target position) and risk-overlay policies; `backtest_portfolio` (position-level, before/after exposure adjustment), divergence gauges, post-mortem, live overlay config generation.
- `quant_api.core` - shared: config objects (reusing `trading.contracts`), catalog reader, artifact writer, pool loader/writer, registry base.

Data: the API resolves market data itself via `ParquetDataCatalog` over the research catalog (`data/catalog`, default VN30F1M 1-minute bars). Users never pass data manually. `pd.read_parquet` is not usable for OHLCV (Nautilus packs values as bytes inside the parquet columns; verified 2026-09-01).

Artifacts: only handoff artifacts are auto-saved - trial ledger (append-only), pool folder + index (alpha files carrying DSL + metadata + spec sheet), weights, weekly slippage summary, risk overlay config. Researcher-facing reports (tear sheet, backtest report, gauge report, post-mortem) stay in-memory with explicit export.

Extension: one registry per slot (`combine_methods`, `sizing_methods`, `risk_policies`, `execution_algorithms`, `ga_fitness`). Defaults are pre-registered and delegate to the Rust engine; practitioners register new methods as plain Python functions for research. Artifacts record method provenance (engine-backed vs python-registered) so a validated method can be migrated into the Rust traits (`CombineMethod`, `SizingMethod`) or live wiring later.

Engine: one additive Rust binding `ga_breed_py` (seeds in, final ranked population out) so the GA can breed from researcher-approved seeds; core GA machinery untouched.

## 2. Rationale

- DEC-005 established the Python-first surface; the raw `alpha_core` bindings are engine functions, not role workflows. The four roles run one shared loop (framework-lifecycle): research replenishes the pool, portfolio combines and refits, execution converts targets to fills, risk owns sizing and the immune system.
- Owner feedback 2026-09-01: seeds are evaluated as single alphas before mining (WorldQuant-style); passing alphas are delivered as a pool folder of per-alpha files; sizing belongs to the risk role, not portfolio; Nautilus native backtest/analyzer are reused before any custom execution simulation; the word "replay" is avoided for risk (portfolio backtest instead); evaluation of registered algorithms is a later phase, not part of this delivery.
- Artifact discipline: only artifacts consumed by another role or the live system are persisted; no decorative files.

## 3. Consequence

- Canon contracts are not changed; module entry points wrap existing engine bindings and `trading` code.
- New ledger test-mapping note TST-011 covers the API contract tests (planned with this change).
- The GA binding change is additive: `ga_best_expression_py` remains; `ga_breed_py` reuses `run_ga` with caller-provided seed ASTs.

## Related notes

- [DEC-005](DEC-005-python-first-api.md) - python-first surface strategy
- [DEC-008](DEC-008-live-wiring-architecture.md) - live wiring reused by the execution and risk modules
