---
doc_id: DEC-014
title: Project north star - replicable systematic-trading framework
type: decision
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [north-star, goal, governance, charter]
source: "owner-approved proposal 2026-08-31 (scope 1); generalises milestone-only goal framings"
design: [OV-HOME, OV-LIFECYCLE]
code: [AGENTS.md, docs/handoffs/HANDOFF-001.md]
---

# DEC-014 - Project North Star: Replicable Systematic-Trading Framework

## 1. Decision

Adopt the north-star charter below as the authoritative statement of the project's ultimate goal. It supersedes milestone-only framings (for example "VN30F1M paper execution") as definitions of the goal: those are the current instantiation, not the end state. The frozen canon in `docs/enhanced/` is untouched; this note is the living interpretation and is itself superseded only by a newer note, never edited in place.

## 2. Ultimate goal

Build and operate a production-grade, replicable systematic-trading framework: a continuous loop that turns data into tested, tradeable alpha across assets and strategy styles, where every component is a reusable subsystem with explicit input/output contracts (per OV-LIFECYCLE). The framework itself is the product - not any single strategy or instrument.

Current instantiation: VN30F1M intraday futures, paper execution on the entrade demo (milestone M1; see `docs/handoffs/`). Known future directions: other asset classes, other venues, other strategy styles (for example market making), and replicating the framework for other research shops.

## 3. The five invariants

Correctness is judged against five invariants, not against task completion:

1. **Measurement first** - trustworthy net-of-cost PnL precedes any trading decision; automation on an uncalibrated harness manufactures overfit alphas at industrial speed.
2. **Inference separated from trading** - research decides in score space; money decisions are centralised and executed once.
3. **Gates before admission** - deflated thresholds, trial accounting, orthogonalization: the system is built against self-deception.
4. **Risk minimum before real money** - hard caps, kill switch, alerts precede any live capital.
5. **Feedback, not line** - live results recalibrate cost models, gates and sizing; the framework self-corrects.

## 4. Goal tree

```text
ultimate goal (this note)
  -> build phases 1-7 (OV-LIFECYCLE)
       -> milestones (current: M1; next: M2, M3)
            -> session tasks
```

Every handoff note in `docs/handoffs/` must restate the ultimate goal in short form plus the current milestone, so any fresh session can navigate without re-deriving. Agents read the north star at session start (top of AGENTS.md) before trusting any other state.

## 5. Anchor rule

Before substantial work, an agent states which component (0-7) and build phase (1-7) of the current instantiation the work serves, and how it generalises beyond that instantiation. Work that conflicts with an invariant, or anchors to no phase/component, is out of scope unless the owner directs otherwise. The rule constrains scope, not reasoning: agents remain free to propose any solution that advances the invariants.

## 6. Related notes

- [HOME](../HOME.md) - ledger charter and index
- [OV-HOME](../../enhanced/HOME.md) - vault entry point (market scope)
- [OV-LIFECYCLE](../../enhanced/framework-lifecycle.md) - components, build phases, runtime loop
