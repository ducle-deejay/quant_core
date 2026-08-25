---
type: overview
stages: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [framework, lifecycle, replication, governance]
aliases: ["Framework Lifecycle", "Build Phases", "Components vs Stages"]
source: "discussion: reframing the documented stages as a replicable framework"
---

# Framework Lifecycle — Components, Build Phases, Runtime Loop

## TL;DR

The eight documents labeled "Stage N" are **pipeline components** — always-on
subsystems with input/output contracts, not one-time phases. Building the system
follows **build phases** whose order deliberately differs from the data-flow
order. Once live, everything runs as a **continuous loop** with feedback edges,
not a straight line.

## The three vocabularies

| Vocabulary | Answers | Lifetime |
|---|---|---|
| **Component** (formerly "Stage") | What does this subsystem consume and produce? | Permanent — runs every session once live |
| **Build phase** | In what order do I construct and turn on components? | One-time per replication |
| **Runtime loop** | How do components interact day-to-day, and what feeds back where? | Continuous |

Terminology rule going forward: *"Stage N"* in the original docs ≡ **"Component
N"** in framework language. Boundaries between components keep their pass/fail
gates — now read as **admission/promotion criteria** (an alpha is *promoted*
into the pool; it does not "finish a stage").

## The eight components

| # | Component | Contract (in → out) | Runtime mode |
|---|---|---|---|
| 0 | Alpha mining | hypotheses/data → score functions + dossiers | batch, continuous replenishment |
| 1 | Canonical simulation | score → canonical position → net PnL dossier | per candidate, vectorized |
| 2 | Evaluation & screening | dossier → IN/OUT + spec sheet | gate on admission |
| 3 | Orthogonalization | candidate + pool → residual verdict | gate on admission |
| 4 | Combination | residual dossiers → composite score | scheduled refits + live weighting |
| 5 | Position construction | composite → target position | every bar |
| 6 | Trade scheduling | target + book → child orders + telemetry | every bar, event-driven |
| 7 | Risk overlay & monitoring | telemetry → interventions/alerts | real-time, independent process |

## Build phases for replication

Build order ≠ data-flow order. Execution and risk minimums must exist before
real money, though they sit late in the flow.

```
Phase 1 — Measurement foundation      : Component 1 harness + cost model calibrate
                                        milestone: any score → trustworthy net PnL
Phase 2 — Research loop (manual mode) : hand-written seeds through Components 1–2
                                        milestone: first alpha passes deflated gates
Phase 3 — Pool & minimal combination  : Components 3–4 (corr filter, then
                                        inverse-vol + equal-weight blend)
                                        milestone: composite beats equal-weight-only
Phase 4 — Sizing + paper execution    : Components 5–6 in paper mode, 2–4 weeks
                                        milestone: paper fills match cost assumptions
Phase 5 — Live small + risk minimum   : Component 7 MINIMUM VIABLE before first
                                        order: hard caps, kill switch, alerts;
                                        ramp-up ladder active
                                        milestone: live-vs-backtest within bands
Phase 6 — Factory automation          : Component 0 machinery (grammar, GA,
                                        registry instrumentation, clustering)
                                        milestone: mined alphas passing gates
Phase 7 — Governance & scale          : families, strategic risk budgets,
                                        regime/time-of-day techniques, HRP
                                        milestone: >1 family, budget review running
```

Rationale worth keeping: Component 7's minimum viable subset precedes all real
capital even though it sits last in the flow — an immune system built after the
first infection is not an immune system. Component 0's automation comes late
because a mining machine amplifies whatever harness it sits on; automating on top
of an uncalibrated harness manufactures overfit alphas at industrial speed.

## The runtime loop

Daily cycle: Components 5–6 run every bar; Component 7 watches continuously;
Components 4–5 weights/budgets adjust slowly (weekly–quarterly); Components 0–3
replenish the pool continuously.

Feedback edges (what makes it a loop, not a line):

- **7 → 1**: measured implementation shortfall recalibrates cost models;
- **7 → 2**: divergence triggers spec-sheet kill criteria; failures logged as
  trials into the registry;
- **2 → 0**: post-mortem findings become new gates and updated family priors for
  the next mining generation;
- **Live fills → 5/6**: slippage attribution feeds sizing buffers and scheduling
  parameters.

Operating cadence: per-bar (5, 6, 7 watch); daily (PnL decomposition report,
registry updates); weekly (slippage review, weight refits); monthly (pool health,
parameter re-sweeps); quarterly (risk budgets, orthogonalization re-runs, harness
version review).

---
## Links
- Up: [[HOME.md]]
- All components: [[stages/stage-0-alpha-mining.md]] … [[stages/stage-7-risk-overlay-monitoring.md]]
- Related: [[concepts/evaluation/trial-count-and-thresholds.md]], [[concepts/evaluation/spec-sheet-and-monitoring.md]],
  [[concepts/risk/divergence-monitoring.md]], [[concepts/evaluation/post-mortem.md]]
