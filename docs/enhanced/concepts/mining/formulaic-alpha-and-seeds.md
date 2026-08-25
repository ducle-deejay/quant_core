---
doc_id: CON-MIN-FORMULAIC-ALPHA
title: Formulaic Alpha and Seeds
type: specification
owner: research
status: approved
version: 1.1
components: [0]
tags: [mining, formulaic-alpha, dsl]
source: "discussion: formulaic-alpha breakdown; DSL anatomy; rule-based vs score-based"
---

# Formulaic Alpha and Seeds

## 1. Summary

A formulaic alpha is an explicit formula over data built from standard operators, encoding one behavioral hypothesis per expression. Seeds are hand-written formulas feeding genetic breeding. Rule-based entry-exit output is a subset of this family.

## 2. Specification

2.1 Canonical reference: "101 Formulaic Alphas" (Kakushadze, WorldQuant, 2015), example `Alpha#6 = -correlation(open, volume, 10)`.

2.2 Two operator families exist. Time-series operators act on one instrument's history: ts_mean, ts_std, delay, delta, ts_rank, rolling correlation. Cross-sectional operators rank or standardize across instruments. Single-instrument time-series trading uses only the time-series family.

2.3 Factory-grade expressions are causal (data at time t or earlier), stateless (no position memory), and vectorizable (one pass over full history).

2.4 Rule-based output (minus-one/zero/plus-one with entry-exit state) is the same family after sign(), thresholds, and memory. Modern factories emit continuous stateless scores instead: combinable, IC-measurable, vectorizable; discretization happens downstream in sizing.

2.5 DSL sections: metadata / data / params / features / rules / signals. The DSL exists so formulas become data - storable, comparable, machine-generatable.

2.6 Why the Chinese assembly line works there: retail-dominated flow preserves behavioral patterns; post-2015 rules fenced out foreign speed competition; inexpensive labor sustains the conveyor. Published formulas die within months - the product is the factory. Transferable to VN30F1M: methodology plus local raw materials. Not transferable: cross-sectional layers, T0 tricks, the published formulas themselves.

---
## Related notes
- [stage-0-alpha-mining](../../stages/stage-0-alpha-mining.md), [ga-machinery](ga-machinery.md), [seed-alpha-demo](../../case-studies/seed-alpha-demo.md)
