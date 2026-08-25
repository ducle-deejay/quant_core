---
doc_id: OV-LIFECYCLE
title: Framework Lifecycle - Components, Build Phases, Runtime Loop
type: overview
owner: research
status: approved
version: 1.1
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [framework, lifecycle, replication, governance]
source: "discussion: reframing the documented stages as a replicable framework; reformatted per REF-STYLE"
---

# Framework Lifecycle - Components, Build Phases, Runtime Loop

## 1. Summary

The eight documents labeled Stage N are pipeline components - always-on subsystems with input/output contracts - not one-time phases. Building the system follows build phases whose order deliberately differs from the data-flow order. Once live, everything runs as a continuous loop with feedback edges, not a straight line. This file defines the three vocabularies needed to talk about the framework without confusing those ideas.

## 2. The three vocabularies

2.1 Component (formerly Stage). Answers: what does this subsystem consume and produce. Lifetime: permanent - runs every session once live.

2.2 Build phase. Answers: in what order components are constructed and switched on. Lifetime: one-time per replication.

2.3 Runtime loop. Answers: how components interact day-to-day and what feeds back where. Lifetime: continuous.

Terminology rule going forward: Stage N in the original docs means Component N in framework language. Boundaries between components keep their pass/fail gates
- read as admission/promotion criteria: an alpha is promoted into the pool, it does not finish a stage.

## 3. The eight components

Component 0 - Alpha mining. Contract: hypotheses and data in -> score functions plus dossiers out. Runtime mode: batch, continuous replenishment.

Component 1 - Canonical simulation. Contract: score series in -> canonical position plus net-PnL dossier out. Runtime mode: per candidate, vectorized.

Component 2 - Evaluation and screening. Contract: dossiers in -> IN/OUT decisions plus spec sheets out. Runtime mode: gate on admission.

Component 3 - Orthogonalization. Contract: candidate plus pool PnLs in -> residual verdict out. Runtime mode: gate on admission.

Component 4 - Combination. Contract: residual dossiers plus standardized scores in -> composite score out. Runtime mode: scheduled refits plus live weighting.

Component 5 - Position construction. Contract: composite score plus risk configuration in -> target position out. Runtime mode: every bar.

Component 6 - Trade scheduling. Contract: target versus current position plus book state in -> child orders plus telemetry out. Runtime mode: every bar, event-driven.

Component 7 - Risk overlay and monitoring. Contract: telemetry plus spec-sheet expectations in -> interventions plus alerts out. Runtime mode: real time, independent process.

## 4. Build phases for replication

Build order is not data-flow order. Execution and risk minimums must exist before real money even though they sit late in the flow.

```text
    Phase 1 - Measurement foundation       : Component 1 harness + cost model
                                             calibrated
                                             milestone: any score -> trustworthy
                                             net PnL
    Phase 2 - Research loop (manual mode)  : hand-written seeds through
                                             Components 1-2
                                             milestone: first alpha passes
                                             deflated gates
    Phase 3 - Pool + minimal combination   : Components 3-4 (correlation filter,
                                             then inverse-vol + equal-weight
                                             blend)
                                             milestone: composite beats
                                             equal-weight-only
    Phase 4 - Sizing + paper execution     : Components 5-6 in paper mode,
                                             2-4 weeks
                                             milestone: paper fills match cost
                                             assumptions
    Phase 5 - Live small + risk minimum    : Component 7 MINIMUM VIABLE before
                                             first order: hard caps, kill switch,
                                             alerts; ramp-up ladder active
                                             milestone: live-versus-backtest
                                             within bands
    Phase 6 - Factory automation           : Component 0 machinery (grammar, GA,
                                             registry instrumentation, clustering)
                                             milestone: mined alphas passing gates
    Phase 7 - Governance + scale           : families, strategic risk budgets,
                                             regime/time-of-day techniques, HRP
                                             milestone: more than one family,
                                             budget review running
```


Rationale worth keeping: Component 7's minimum viable subset precedes all real capital even though it sits late in the flow - an immune system built after the first infection is not an immune system. Component 0's automation comes late because a mining machine amplifies whatever harness it sits on; automating on top of an uncalibrated harness manufactures overfit alphas at industrial speed.

## 5. The runtime loop

5.1 Daily cycle. Components 5 and 6 run every bar; Component 7 watches continuously; Components 4 and 5 adjust weights and budgets slowly (weekly to quarterly); Components 0 to 3 replenish the pool continuously.

5.2 Feedback edges - what makes it a loop, not a line:

- 7 -> 1: measured implementation shortfall recalibrates cost models;
- 7 -> 2: divergence triggers spec-sheet kill criteria; failures logged as trials into the registry;
- 2 -> 0: post-mortem findings become new gates and updated family priors for the next mining generation;
- live fills -> 5 and 6: slippage attribution feeds sizing buffers and scheduling parameters.

5.3 Operating cadence. Per bar: Components 5 and 6 execute, Component 7 watches. Daily: PnL decomposition report, registry updates. Weekly: slippage review, weight refits. Monthly: pool health checks, parameter re-sweeps. Quarterly: risk budgets, orthogonalization re-runs, harness version review.

## 6. Related notes

- [[HOME.md]] - vault entry point and index
- [[stages/stage-0-alpha-mining.md]] through [[stages/stage-7-risk-overlay-monitoring.md]]
- the eight component specifications
- [[concepts/evaluation/trial-count-and-thresholds.md]] - trial ledger behind the dynamic thresholds referenced above
- [[concepts/evaluation/spec-sheet-and-monitoring.md]] - expectations consumed by divergence monitoring
- [[concepts/risk/divergence-monitoring.md]] - gauges and escalation ladder
- [[concepts/evaluation/post-mortem.md]] - failure dissection feeding edge 2 -> 0
