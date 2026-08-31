---
doc_id: TST-011
title: quant_api role-module contract tests
type: test-mapping
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [api, tests, quant-api, mapping]
source: "integrator mapping for the quant_api delivery (DEC-017)"
design: []
code: [src/quant_api]
test: [src/quant_api/tests/test_core.py, src/quant_api/tests/test_research.py, src/quant_api/tests/test_risk.py, src/quant_api/tests/test_portfolio.py, src/quant_api/tests/test_execution.py, src/quant_api/tests/test_integration.py]
---

# TST-011 - quant_api role-module contract tests

## 1. What is protected

The quant_api role-scoped Python API surface defined in decision note
DEC-017: shared core (config, catalog data access, artifact writers, pool,
registries), the four role modules (research, portfolio, execution, risk),
and the full-chain integration (seed -> evaluation -> GA mining -> pool
delivery -> combination -> portfolio backtest).

## 2. Mapping

| Note | What the tests protect | Runner |
|---|---|---|
| DEC-017 | Registry semantics (duplicate rejection, provenance, replace) | test_core.py: test_registry_semantics |
| DEC-017 | Pool folder round-trip (entry file + index + corrupt-entry guard) | test_core.py: test_pool_round_trip |
| DEC-017 | Handoff artifact writers (trial ledger append-only, weights, slippage, overlay config) | test_core.py: test_artifact_writers |
| DEC-017 | Catalog data access via ParquetDataCatalog (window + full history) | test_core.py: test_data_catalog_window |
| DEC-017, Component 2 - Evaluation and Screening | Seed canonicalization and invalid-syntax rejection | test_research.py: test_validate_seed_canonicalizes |
| DEC-017, Component 1 - Canonical Simulation | Single-alpha evaluation pipeline -> TearSheet metrics and verdict | test_research.py: test_evaluate_seed_verdicts_synthetic, test_evaluate_seed_rejects_invalid |
| DEC-017 | GA fitness registry engine default | test_research.py: test_ga_fitness_registry_engine_default |
| DEC-017 | GA breeding determinism + empty/invalid seed guards | test_research.py: test_mine_seeds_deterministic, test_mine_seeds_rejects_empty_and_invalid |
| DEC-017, Component 2 | Batch funnel with trial-ledger accounting | test_research.py: test_screen_batch_records_trials |
| DEC-017 | Spec sheet fields and pool delivery (IN only, index regeneration) | test_research.py: test_build_spec_sheet_fields, test_deliver_to_pool_round_trip |
| DEC-017, Component 3 - Orthogonalization | Residual verdict INCREMENTAL/REDUNDANT | test_portfolio.py (orthogonalize cases) |
| DEC-017, Component 4 - Combination | equal_weight/inverse_vol engine-backed combine, research weights mirror engine composite | test_portfolio.py (registry, combine, parity cases) |
| DEC-017 | Weight refit handoff artifact (save/no-save, window) | test_portfolio.py (refit cases) |
| DEC-017 | Monthly health report structure and verdict rule | test_portfolio.py (health-report cases) |
| DEC-017, Component 5 - Position Construction | Sizing registry defaults delegate to engine bindings | test_risk.py: test_sizing_registry_defaults |
| DEC-017, Component 7 - Risk Overlay and Monitoring | Trigger-matrix policy default; portfolio backtest before/after with risk-process metrics; loss-limit HALTED path | test_risk.py: test_risk_policies_trigger_matrix_default, test_backtest_portfolio_shape, test_backtest_portfolio_loss_halt |
| DEC-017, Component 7 | Divergence gauges 1-4 with bands and n/a handling | test_risk.py: test_divergence_gauges |
| DEC-017, Component 7 | Post-mortem parsing of session decision/risk logs + recommendations | test_risk.py: test_post_mortem_parses_session_dir |
| DEC-017 | Live overlay config handoff artifact | test_risk.py: test_build_overlay_config_saves |
| DEC-017, Component 6 - Trade Scheduling | Urgency math act-now/slice; algorithm registry (marketable_limit engine, twap python) | test_execution.py: test_urgency_analysis_math, test_execution_algorithms_registry |
| DEC-017, feedback 7->1 | Weekly slippage report decomposition + handoff artifact | test_execution.py: test_slippage_report_synthetic |
| DEC-017 | Nautilus BacktestEngine offline execution backtest (fills, slippage, no rejects) | test_execution.py: test_backtest_execution_smoke |
| DEC-017 | Full chain: seed -> evaluate -> mine -> pool -> combine -> refit -> portfolio backtest on real catalog data | test_integration.py: test_full_chain |

## 3. How to run

```sh
for t in core research risk portfolio execution; do
  .venv/bin/python3 src/quant_api/tests/test_$t.py
done
.venv/bin/python3 src/quant_api/tests/test_integration.py
```

All runners are plain assert scripts (pytest not installed); every write
goes to a tempfile directory except the integration test's trial-ledger
smoke, which also uses a temp root.

## 4. Status

48 quant_api tests + 1 integration chain, all green on 2026-08-31
(core 4, research 10, risk 8, portfolio 22, execution 4, integration 1).
Rust engine: 226 unit tests green; Python parity suite 21/21 green.
Ledger sweep clean.
