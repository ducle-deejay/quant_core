---
doc_id: PLAN-002
title: QuantCore Implementation Plan v2
type: overview
owner: research
status: approved
version: 2.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [plan, roadmap, task-checklist]
source: "restructured from batch-based format to task-checklist format for auditability"
---

# QuantCore Implementation Plan v2

## How to audit this document

Every task is an independent block containing: identifier, description, target
files, dependencies, completion criteria, and current status. No task requires
context from another task's description. Component references use full names
("Component 1 - Canonical Simulation"), never abbreviations.

Status values: `[x]` = done, `[ ]` = pending, `[~]` = partially done.

## Progress snapshot (updated 2026-08-26)

    Complete            : 30 of 32 tasks
    Partially complete  : 2  (T023 drawdown-live feed, T031 seed-comparison
                          entry point)
    Pending             : 0
    Python API          : full-surface bindings live (DEC-005); 21-check
                          parity suite green on Python 3.14
    Quality gates       : 222 Rust unit tests green; system-audit battery
                          passes on real VN30F1M data; ledger sweep clean
    Beyond-plan additions since v2.0: evaluation/screening module,
                          bin/system_audit battery, bin/batch_verify,
                          examples/ rename, governance kit + ledger

---

## Section A — Foundation (no dependencies beyond Rust toolchain)

### TASK 001: Scaffold Rust workspace

File: Cargo.toml (workspace root), crates/alpha-core/Cargo.toml, .gitignore
Depends on: nothing
Done when: cargo build succeeds with zero errors.
Status: [x] Complete.

### TASK 002: Implement harness configuration

File: crates/alpha-core/src/harness_config.rs
Depends on: TASK 001
Deliverable: HarnessConfig struct with span, z_window, band, cap,
cost_per_side fields plus Default implementation matching docs/plan.md
section 5 parameter table.
Verified by: cargo build passes; Default values match documented values.
Status: [x] Complete.

### TASK 003: Implement typed symbol registry

File: crates/alpha-core/src/notation.rs
Depends on: TASK 001
Deliverable: Typed constants or enums for every symbol in the notation
registry (reference/notation.md). Prevents typo-based bugs where two
different concepts accidentally share a symbol name.
Verified by: cargo build passes; every formula symbol resolves to a
registry entry.
Status: [x] Complete (NotationRegistry with collision guard, 4 unit
tests; verified during governance-kit audit).

---

## Section B — Component 1: Canonical Simulation

All tasks produce pure functions operating on score series arrays.
No side effects. Anti-lookahead enforced by signature design.

### TASK 004: Implement EWMA smoothing (Step A)

File: crates/alpha-core/src/canonical/mapping.rs
Depends on: TASK 002
Formula:

    s_smooth(t) = lambda_s * score(t) + (1 - lambda_s) * s_smooth(t-1)

    lambda_s    EWMA smoothing weight = 2 / (span + 1)

Done when: output matches numpy pandas.Series.ewm(span=span).mean()
within floating-point tolerance on identical input.
Status: [x] Complete.

### TASK 005: Implement rolling z-score (Step B)

File: crates/alpha-core/src/canonical/mapping.rs
Depends on: TASK 004
Formula:

    z(t) = ( s_smooth(t) - mean_w(t) ) / std_w(t)

    mean_w(t)   rolling mean of s_smooth over trailing window w bars
    std_w(t)    rolling standard deviation over same window

Done when: output matches pandas rolling mean/std computation within
floating-point tolerance; zero-std windows produce zero z-scores.
Status: [x] Complete.

### TASK 006: Implement no-trade band then leverage cap (Steps C and D)

File: crates/alpha-core/src/canonical/mapping.rs
Depends on: TASK 005
Logic:

    if abs( z(t) - p(t-1) ) > band : p(t) = clip( z(t), -L, +L )
    else                             : p(t) = p(t-1)

Done when: band correctly creates dead-zone; cap prevents position from
exceeding leverage limit; unit tests verify both branches.
Status: [x] Complete.

### TASK 007: Implement canonical mapping orchestrator

File: crates/alpha-core/src/canonical/mapping.rs
Depends on: TASK 004, 005, 006
Deliverable: canonical_map(score, config, bars_per_day) -> CanonicalResult
containing position series, turnover series, trades per day.
Verified by: integration test on real VN30F1M.csv data produces non-zero
positions after warmup period.
Status: [x] Complete.

### TASK 008: Implement PnL identity

File: crates/alpha-core/src/canonical/pnl.rs
Depends on: TASK 007 (consumes canonical position output)
Formula:

    pnl(t)     = p(t-1) * r(t) - c * abs( p(t) - p(t-1) )

    pnl(t)     profit-and-loss for bar t
    p(t-1)     position decided at end of bar t-1 (anti-lookahead)
    r(t)       asset return over bar t
    c          cost per unit notional per side
    abs(...)   fees are direction-blind

Done when: three unit tests pass verifying basic PnL, anti-lookahead
placement, and direction-blind turnover counting.
Status: [x] Complete (3/3 tests pass).

### TASK 009: Implement Sharpe ratio and maximum drawdown metrics

File: crates/alpha-core/src/canonical/metrics.rs
Depends on: TASK 008
Deliverable: sharpe(daily_pnl) -> annualized Sharpe ratio;
max_drawdown(pnl_series) -> maximum peak-to-trough decline.
Status: [x] Complete.

---

## Section C — Component 2: Evaluation and Screening

### TASK 010: Implement Rank IC at horizon with block t-statistic

File: crates/alpha-core/src/evaluation/ic_ladder.rs
Depends on: TASK 007
Formula:

    IC(h) = Spearman rank correlation between score(t)
            and cumulative forward return from t+1 through t+h

Aggregated into daily blocks; reported as mean with block t-statistic.
Done when: computed IC matches pandas rolling correlation within tolerance
on real VN30F1M.csv data.
Status: [x] Complete.

### TASK 011: Implement IC ladder across multiple horizons

File: crates/alpha-core/src/evaluation/ic_ladder.rs
Depends on: TASK 010
Deliverable: ic_ladder(score, ret, horizons, window, bars_per_day)
-> Vec of results, one per horizon in the input list.
Status: [x] Complete.

### TASK 012: Implement walk-forward block stability analysis

File: crates/alpha-core/src/evaluation/walk_forward.rs
Depends on: TASK 008
Deliverable: walk_forward(daily_pnl, block_days) -> positive percentage,
worst block Sharpe, per-block statistics.
Status: [x] Complete.

### TASK 013: Implement deflated Sharpe Ratio calculation

File: crates/alpha-core/src/evaluation/gates.rs (or separate module)
Depends on: TASK 012 and TASK 014
Formula: Bailey and Lopez de Prado deflated Sharpe adjusts observed
maximum Sharpe for expected maximum of N random trials, using skewness,
kurtosis, and sample length.
Done when: threshold rises monotonically with trial count and converges
to zero-inflation case when N equals one.
Status: [x] Complete (deflated_threshold plus PSR-style
deflated_sharpe_probability; both wired into evaluate_gate as checks;
monotonicity and single-trial degeneracy covered by contract tests -
see reconciliation REC-002).

### TASK 014: Implement trial ledger (persistence layer)

File: crates/alpha-core/src/evaluation/trial_ledger.rs
Depends on: nothing
Deliverable: append-only log recording hash(code_version, params, data_range)
and result for every evaluation event. Supports deduplication by hash and
counting unique entries for effective-N estimation.
Verified by: adding entries, deduplicating identical hashes, counting
unique evaluations.
Status: [x] Complete (append-only entries, FNV-1a hash dedup,
unique_count and effective_n clustering, save/load persistence;
7 unit tests).

### TASK 015: Implement parameter plateau sweep automation

File: crates/alpha-core/src/evaluation/plateau_sweep.rs
Depends on: TASK 007
Deliverable: sweep alpha parameters on grid around chosen values,
compute metric at each point, detect plateau versus sharp peak by
measuring neighbor variance around optimum.
Verified by: known plateau passes; known single-point peak fails.
Status: [x] Complete (make_grid and detect_plateau; flat-neighborhood
plateau accepted and sharp peak rejected by dedicated tests - 9 total).

### TASK 016: Implement gate evaluation criteria

File: crates/alpha-core/src/evaluation/gates.rs
Depends on: TASK 009, 011, 012, 013, 015
Deliverable: evaluate_gate(input, criteria) -> list of named checks
with pass/fail booleans; all must hold simultaneously for overall PASS.
Default criteria match docs/plan.md section on Stage 2 gates.
Status: [x] Complete (seven named checks including expected-maximum
threshold and PSR spurious-probability gate; integration finished -
see REC-002).

---

## Section D — Component 3: Orthogonalization

### TASK 017: Implement orthogonalization via OLS residual regression

File: crates/alpha-core/src/orthogonalization.rs
Depends on: TASK 008
Deliverable: orthogonalize(candidate, pool) -> residual series after
regressing out all pool columns via Gaussian elimination with partial
pivoting.
Done when: two unit tests pass - one verifying explained part removed
from correlated alpha, one verifying uncorrelated alpha signal preserved.
Status: [x] Complete (2/2 tests pass after threshold fix).

---

## Section E — Component 4: Combination

### TASK 018: Define CombineMethod trait

File: crates/alpha-core/src/strategies/combination/mod.rs
Depends on: nothing
Deliverable: pub trait CombineMethod with combine(scores) -> composite
and name() -> str methods.
Status: [x] Complete (implemented by Subagent C).

### TASK 019: Implement inverse-volatility weighting practical case

File: crates/alpha-core/src/strategies/combination/inverse_vol.rs
Depends on: TASK 018
Deliverable: InverseVol struct implementing CombineMethod. Weights
proportional to inverse PnL volatility, normalized, capped. Includes
EqualWeight benchmark implementing same trait. Water-filling bisection
for cap compliance.
Verified by: fifteen unit tests covering weights sum to one, caps respected,
zero-vol safety, NaN exclusion, single-alpha handling.
Status: [x] Complete (15/15 tests pass via Subagent C).

### TASK 020: Implement composite score computation

File: crates/alpha-core/src/combination.rs
Depends on: TASK 018
Deliverable: composite_score(scores, weights) -> weighted sum producing
one continuous series from k standardized inputs.
Verified by: two unit tests covering basic combination and zero-weight
exclusion.
Status: [x] Complete (2/2 tests pass).

---

## Section F — Component 5: Position Construction

### TASK 021: Define SizingMethod trait

File: crates/alpha-core/src/strategies/sizing/mod.rs
Depends on: nothing
Deliverable: pub trait SizingMethod with compute(score, vol_est) ->
target positions and name() -> str.
Status: [x] Complete (implemented by Subagent B).

### TASK 022: Implement volatility targeting practical case

File: crates/alpha-core/src/strategies/sizing/vol_target.rs
Depends on: TASK 021
Deliverable: VolTarget struct computing p = z * (vol_target / vol_est)
with zero-vol safety guard. Includes VolTargetWithFloor variant applying
minimum volatility floor to prevent leverage explosion during quiet regimes.
Verified by: eight unit tests covering exact scaling math, floor behavior,
zero-vol safety, empty input, trait-object dispatch.
Status: [x] Complete (8/8 tests pass via Subagent B).

### TASK 023: Implement drawdown overlay multiplier integration

File: crates/alpha-core/src/strategies/sizing/vol_target.rs (extension)
Depends on: TASK 022
Deliverable: multiply vol-targeted position by m from pre-committed
drawdown table. Table frozen before live deployment; changes require
logged change-review cycle.
Status: [~] Partially complete - DrawdownLadder with DEFAULT_BANDS rule
table built and covered by 18 offline tests; remaining work is multiplying
the vol-targeted position inside the live sizing path and feeding real
equity-curve updates from deployment.

---

## Section G — Expression Engine (Mining Strategies)

### TASK 024: Implement DSL tokenizer and recursive descent parser

File: crates/alpha-core/src/strategies/mining/expression_parser.rs
Depends on: nothing
Deliverable: parse(dsl_string) -> Result of AstNode tree representing
the alpha expression. Grammar supports arithmetic operators, data fields,
time-series functions with window parameters.
Done when: parser round-trips via Display impl; error cases report
byte positions; precedence and associativity verified by tests.
Status: [x] Complete (implemented by Subagent A; mining tests pass).

### TASK 025: Implement shared computation DAG builder

File: crates/alpha-core/src/strategies/mining/dag_builder.rs
Depends on: TASK 024
Deliverable: build_dag(asts) -> ComputationDag with deduplicated nodes,
dependency edges, topological execution order, and root node mappings.
Deduplication uses structural hashing so identical subtrees share nodes
regardless of which alpha referenced them.
Done when: shared sub-expressions appear once in DAG; execution order is
topologically sorted; root mappings cover all input alphas.
Status: [x] Complete (implemented by Subagent A).

### TASK 026: Implement vectorised batch executor

File: crates/alpha-core/src/strategies/mining/batch_executor.rs
Depends on: TASK 025
Deliverable: execute_batch(dag, data, roots) -> matrix where row i is
the score series for alpha i. Rolling operations use sliding-window
accumulators for O(1) amortised per-bar updates. NaN propagation follows
documented contracts.
Done when: end-to-end evaluation matches naive per-alpha independent
computation; unequal column lengths padded with NaN; missing fields
produce NaN columns.
Status: [x] Complete (implemented by Subagent A).

### TASK 027: Implement GA breeding engine (practical case for ScoreGenerator)

File: crates/alpha-core/src/strategies/mining/seed_ga.rs
Depends on: TASK 024, 025, 026
Deliverable:
- Tournament selection on fitness scores
- Subtree crossover between expression trees
- Mutation: random operator substitution, field swap, window perturbation
- Population management: elitism, diversity maintenance, generation tracking
- Integration with batch_executor for vectorised fitness evaluation
Done when: GA loop runs for specified generations, population fitness
improves measurably, best individual is extractable as DSL string.
Status: [x] Complete (tournament selection, subtree crossover, four
mutation operators, elitism, canonical-form invariant; end-to-end test
drives generations through batch_executor fitness - 21 tests).

---

## Section H — Python Bindings

### TASK 028: Set up PyO3/maturin build backend

File: pyproject.toml, crates/alpha-core/Cargo.toml
Depends on: TASK 001
Deliverable: maturin build backend configured; PyO3 optional dependency
added to Cargo.toml; python-source directory declared.
Status: [x] Complete (implemented by Subagent D).

### TASK 029: Create Python package init

File: python/quantcore/__init__.py
Depends on: TASK 028
Deliverable: __init__.py with package docstring and version.
Status: [x] Complete (implemented by Subagent D).

### TASK 030: Export Rust functions to Python via PyO3 macro

File: crates/alpha-core/src/lib.rs (addition)
Depends on: TASK 028
Deliverable: #[pyfunction] wrappers around canonical_map, compute_pnl,
ic_ladder enabling researchers to call Rust functions from Python notebooks.
Done when: python import quantcore works; canonical_map called from Python
produces identical output to Rust-native call on same input.
Status: [x] Complete - full-surface bindings shipped under DEC-005:
18 exported functions and 6 result classes across Components 0-5,
pyo3 upgraded to 0.29 for Python 3.14, maturin develop verified in
.venv, and a 21-check parity suite (examples/parity_full_surface.py)
passes end-to-end.

---

## Section I — End-to-End Verification on Real Data

### TASK 031: Run full pipeline on real VN30F1M.csv

File: crates/alpha-core/src/bin/alphascreen.rs
Depends on: Sections B through G
Data: data/VN30F1M.csv (472809 one-minute bars, 1972 sessions,
2018-09-25 to 2026-08-21, close range 563.0 to 2115.6)
Done when: pipeline loads real data without errors, generates six seed
alphas with varying lookback windows, runs canonical simulation producing
non-zero positions, computes meaningful Sharpe ratios and Information
Coefficient values, outputs formatted comparison table.
Current status: pipeline runs end-to-end without panics (NaN comparator
fixed under TASK 032). Superseded in scope by bin/batch_verify, which
pushes 250 grammar-guided expressions through the full stack per run;
alphascreen remains the seed-based variant comparison entry point.
Status: [~] Partially complete - functional; broader coverage delegated
to batch verification.

### TASK 032: Fix NaN panic in max_by comparator

File: crates/alpha-core/src/bin/alphascreen.rs
Depends on: TASK 031 diagnosis
Fix: replace .unwrap() on partial_cmp with explicit NaN handling -
NaN sorts as less than any value (consistent with "invalid result ranks
below valid").
Status: [x] Complete (fixed during debugging session).

---

## Extension Points (documented for future research, not in current scope)

These are NOT built in this plan. They are catalogued with entry conditions
so researchers know when to activate them. Full details in concept notes.

### Immediate extensions (implementable now on historical data)

| Extension | Component | Entry condition | Concept note |
|---|---|---|---|
| Rank/percentile normalization | Combination | Day one | supplementary-techniques |
| Veto/filter gates | Combination | Depth/vol signals available | supplementary-techniques |
| Deflated Sharpe | Evaluation | Trial ledger active | trial-count-and-thresholds |
| Permutation null calibration | Evaluation | Harness stable | trial-count-and-thresholds |
| Harvey-Liu haircuts | Evaluation | Multiple-testing correction needed | trial-count-and-thresholds |
| Regime slice gate | Evaluation | Regime classification defined | post-mortem |
| Yang-Zhang volatility estimator | Simulation | Minute-bar data available | vol-targeting |
| Volatility stress buffer | Simulation | Post-shock data collected | vol-targeting |

### Extensions requiring live data

| Extension | Component | Entry condition | Concept note |
|---|---|---|---|
| Meta-labeling | Sizing multiplier | Thousands of live episodes | meta-labeling |
| Learned sizing (RL/SL) | Sizing stack | Years of live fills | china-sizing-stack |
| Impact model | Cost model | Live fill calibration data | cost model discussion |
| End-to-end optimizer | Replaces Components 4+5 boundary | Calibrated cost model | supplementary-techniques |
| Time-of-day calibration | Weight vectors | Real fill quality per session bucket | supplementary-techniques |
| Multi-broker routing | Execution redundancy | Scale demands broker diversity | order-state-machine |
| Chaos drill framework | Failure injection testing | Running system with monitoring | defense-layers |
| Regime classifier live feed | Budget preset switching | Validated regime definitions | china-two-layer-architecture |

### Computational extensions (no Nautilus needed)

| Extension | Component | Entry condition | Concept note |
|---|---|---|---|
| HRP allocation | Combination | Pool > one hundred members | allocation-taxonomy |
| Cluster-then-budget automated | Combination | Families lack semantics | allocation-taxonomy |
| Online learning allocation | Combination | Performance tracking active | allocation-taxonomy |
| Kalman filter on IC weights | Combination | Stable rolling estimates | allocation-taxonomy |
| Black-Litterman blending | Combination | Family expectations quantified | allocation-taxonomy |
| Forward-selection ensembling | Combination | Out-of-sample validation infra | allocation-taxonomy |
| CPPI-style floor protection | Sizing | Drawdown tolerance calibrated | position-sizing-methods |
| Fractional Kelly anchor | Sizing | Live performance data | position-sizing-methods |
| Gap-adjusted cap refinement | Sizing | Historical gap analysis done | vol-targeting |
| Signal-confidence sizing variant | Sizing | Signal strength distribution known | position-sizing-methods |

---

## Dependency graph summary

    Section A (Foundation)
      T001 -> T002 -> T003 (notation registry)
                    |
                    v
    Section B (Canonical Simulation)
      T004 -> T005 -> T006 -> T007 -> T008 -> T009
                                             |
                                             v
    Section C (Evaluation)
      T010 -> T011                           T012 (walk-forward)
                                                    |
                                             T013 (deflated Sharpe, needs T014)
                                             T014 (trial ledger)
                                             T015 (plateau sweep)
                                             T016 (gate criteria eval)
                                                    |
    Section D (Orthogonalization)                   |
      T017 ------------------------------------------> Stage 2 screening ready
                                                                     |
    Section E (Combination)                                         |
      T018 -> T019 -> T020                                          |
                                                                     v
    Section F (Sizing)                                      COMPOSITE SCORE
      T021 -> T022 -> T023                                          |
                                                                     v
    Section G (Expression Engine)                          STAGE 5 SIZING
      T024 -> T025 -> T026 -> T027                                 |
                                                                    |
    Section H (Python Bindings)                                    |
      T028 -> T029 -> T030                                          |
                                                                     v
    Section I (End-to-End)                              LIVE EXECUTION
      T031 + T032
