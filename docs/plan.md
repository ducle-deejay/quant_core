---
doc_id: PLAN-001
title: QuantCore Implementation Plan
type: overview
owner: research
status: approved
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [plan, roadmap, replication]
source: "consolidated from all discussion decisions; snapshot for Phase 1 kickoff"
---

# QuantCore Implementation Plan

## 1. Project identity

- **Name**: quantcore (crate/package), quant_core (repo folder)
- **Architecture**: Rust core + Python bindings via PyO3/maturin
- **Integration**: Nautilus Trader adapter (future, Phase 4+)
- **Pattern**: 1 practical case per component + extension points for researchers

## 2. Directory structure

```
quant_core/
├── .gitignore
├── Cargo.toml                          <- Rust workspace root
├── pyproject.toml                      <- maturin build backend
│
├── crates/
│   └── alpha-core/
│       ├── Cargo.toml
│       └── src/
│           ├── lib.rs                  # public API, re-exports
│           ├── harness_config.rs       # versioned harness params
│           ├── notation.rs             # symbol registry (typed structs)
│           ├── canonical/
│           │   ├── mod.rs              # C1: orchestration
│           │   ├── mapping.rs          # EWMA -> z -> band -> cap
│           │   ├── pnl.rs              # PnL identity + turnover
│           │   └── metrics.rs          # batch Sharpe, IC, cost drag
│           ├── evaluation/
│           │   ├── mod.rs              # C2: orchestration
│           │   ├── ic_ladder.rs        # Rank IC at horizons, block t-stat
│           │   ├── walk_forward.rs     # rolling blocks, % positive
│           │   ├── plateau.rs          # parameter sweep, plateau detection
│           │   └── gates.rs            # deflated threshold, acceptance rules
│           ├── orthogonalization.rs    # C3: residual regression
│           └── combination.rs          # C4: composite score computation
│
├── strategies/
│   ├── mining/
│   │   ├── mod.rs                      # trait ScoreGenerator
│   │   ├── seed_ga.rs                  # practical case: seeds + GA search
│   │   ├── expression_parser.rs        # DSL string -> AST
│   │   ├── dag_builder.rs              # AST -> shared computation graph
│   │   └── batch_executor.rs           # DAG -> vectorised score matrix
│   ├── sizing/
│   │   ├── mod.rs                      # trait SizingMethod
│   │   ├── vol_target.rs               # practical case
│   └── combination/
│       ├── mod.rs                      # trait CombineMethod
│       ├── inverse_vol.rs              # practical case
│
├── python/
│   └── quantcore/
│       └── __init__.py                 # PyO3 bindings
│
├── integration/
│   └── nautilus_adapter.py             # future: Nautilus bridge
│
├── data/                               # gitignored
├── research/                           # verify/demo scripts (committed)
└── docs/
    ├── enhanced/                       # vault documentation (committed)
    └── original/                       # frozen originals (committed)
```

## 3. Gitignore

```
data/
.venv/
.uv_cache/
.uv-tmp/
target/
__pycache__/
*.egg-info/
```

## 4. Pattern: 1 practical case + extension points

Each component exposes a trait defining its input/output contract. One
practical case implements the trait and ships with the core. Researchers add
new implementations without touching core code.

| Component | Trait | Practical case | Future extensions |
|---|---|---|---|
| C0 Mining | ScoreGenerator | seed_ga: seeds + GA search | ML generator, symbolic regression |
| C4 Combination | CombineMethod | inverse_vol + equal-weight blend | risk parity, HRP, ML stacking |
| C5 Sizing | SizingMethod | vol_target + drawdown overlay | Kelly variants, CPPI, learned sizing |

Governance:

- core/: changes only by research lead, harness version bump per quarter
- strategies/ defaults: researcher implements + review after walk-forward pass
- strategies/ new: free to experiment, must pass same gate before promotion

## 5. Canonical parameters (one set per batch)

| Param | Initial value | Calibrated by |
|---|---|---|
| span (EWMA) | 8 bars | grid {4,8,16,32}, pool-aggregate net Sharpe |
| z_window | 480 bars | statistical stability + seasonality |
| band | 0.50 | grid sweep, plateau center on train |
| cap L | +/-2.0 | min(margin, gap stress, regulatory) less safety factor |
| c (cost/side) | fee + half_spread + buffer | calibrated from live fills |

Frozen as harness version. Changes = bump version = re-run entire registry.
Review cadence: quarterly or on significant regime change.

Buffer is adjustable by researcher through harness config. Impact model is a
future extension requiring live fill calibration data.

## 6. Component 1 output (per alpha)

    OUTPUT per alpha:
      1. daily_net_pnl[]     -> Sharpe, MDD, % positive blocks
      2. daily_gross_pnl[]   -> cost drag = 1 - net/gross
      3. score_series[]      -> Rank IC ladder, decay profile
      4. turnover_annualized -> slot ceiling check
      5. metadata            -> params hash, code version, trial count

Sufficient for Stage 2 to grade both forecast layer and economics layer.

## 7. Cost model

    c = fee_side + half_spread_rel + buffer

Buffer is adjustable by researcher through harness config. Impact model is a
future extension at Stage 6 execution layer, not needed at screening stage.
Buffer approximates unmodeled execution frictions (slippage beyond quote,
partial fills, decision-to-fill drift). Calibrated downward from live fills,
never guessed upward.

## 8. Build phases

    Phase 1 - Measurement foundation        : canonical.rs + harness_config.rs
                                              milestone: any score -> trustworthy net PnL

    Phase 2 - Research loop (manual mode)   : hand-written seeds through Components 1-2
                                              milestone: first alpha passes deflated gates

    Phase 3 - Pool + minimal combination    : Components 3-4 (corr filter, then
                                              inverse-vol + equal-weight blend)
                                              milestone: composite beats equal-weight-only

    Phase 4 - Sizing + paper execution      : Components 5-6 in paper mode, 2-4 weeks
                                              milestone: paper fills match cost assumptions

    Phase 5 - Live small + risk minimum     : Component 7 MINIMUM VIABLE before first
                                              order: hard caps, kill switch, alerts;
                                              ramp-up ladder active
                                              milestone: live-vs-backtest within bands

    Phase 6 - Factory automation            : Component 0 machinery (grammar, GA,
                                              registry instrumentation, clustering)
                                              milestone: mined alphas passing gates

    Phase 7 - Governance + scale            : families, strategic risk budgets,
                                              regime/time-of-day techniques, HRP
                                              milestone: more than one family,
                                              budget review running

Rationale: Component 7 minimum viable precedes real capital even though it sits
last in the data flow. Component 0 automation comes last because a mining machine
amplifies whatever harness it sits on.

Build order differs from data-flow order by design.

## 9. Runtime loop

Daily cycle: Components 5 and 6 run every bar; Component 7 watches continuously;
Components 4 and 5 adjust weights and budgets slowly; Components 0 to 3
replenish the pool continuously.

Feedback edges:

    7 -> 1 : measured implementation shortfall recalibrates cost models
    7 -> 2 : divergence triggers spec-sheet kill criteria; failures logged as trials
    2 -> 0 : post-mortem findings become new gates and updated family priors
    fills -> 5/6 : slippage attribution feeds sizing buffers and scheduling parameters

Operating cadence: per bar (5, 6 execute; 7 watches); daily PnL decomposition
report; weekly slippage review; monthly pool health; quarterly risk budgets.

## 10. Verification checklist (run after every phase)

- [ ] All path-wikilinks resolve to existing files
- [ ] All formula blocks have adjacent variable definition lists
- [ ] Clause numbering matches parent section number
- [ ] No TL;DR headings
- [ ] No fake indented lists
- [ ] Code fences balanced per file
- [ ] No special characters banned by style guide
- [ ] doc_id unique across vault
- [ ] Every file linked from HOME or reachable transitively
