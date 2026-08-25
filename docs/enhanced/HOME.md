---
doc_id: OV-HOME
title: Trading System Knowledge Vault - Home
type: index
owner: research
status: approved
version: 1.1
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [moc, home]
aliases: ["Home", "MOC", "Map of Content"]
source: "vault index; reformatted per REF-STYLE"
---

# HOME - Trading System Knowledge Vault

Second-brain vault for the systematic trading pipeline designed for VN30F1M intraday, extensible to BTC perpetual. Frozen first-presentation documents live in docs/original/pipeline_stages. This vault integrates every follow-up discussion in shop-standard format defined by [style-guide](style-guide.md).

## 1. How to navigate

1.1 Humans start at the component list below and follow path-style wikilinks of the form [stage-6-trade-scheduling](stages/stage-6-trade-scheduling.md). Vault must be rooted at docs/enhanced (or a parent) for resolution.

1.2 Agents rely on predictable paths (stages, concepts by domain), YAML front matter with doc_id and components, and plain-markdown basenames as links - greppable without Obsidian.

1.3 One idea per concept note. Stage hubs hold flow plus verbatim core. Duplicates forbidden; link instead.

1.4 Preservation rule: originals are read-only. Corrections appear here as Clarification paragraphs pointing back to the original passage.

## 2. The eight components

- Component 0 - Alpha mining: [stage-0-alpha-mining](stages/stage-0-alpha-mining.md) - DSL grammar x seeds x GA -> thousands of stateless scores
- Component 1 - Canonical simulation: [stage-1-canonical-simulation](stages/stage-1-canonical-simulation.md) - one uniform score-to-position mapping -> comparable net PnL dossier
- Component 2 - Evaluation and screening: [stage-2-evaluation-screening](stages/stage-2-evaluation-screening.md) - gates: information, cost survival, stability, deflated thresholds
- Component 3 - Orthogonalization: [stage-3-orthogonalization](stages/stage-3-orthogonalization.md) - admit only incremental value versus the pool
- Component 4 - Combination: [stage-4-combination](stages/stage-4-combination.md) - residual dossiers -> composite score through governance
- Component 5 - Position construction: [stage-5-position-construction](stages/stage-5-position-construction.md) - vol targeting stack -> target position; risk begins here
- Component 6 - Trade scheduling: [stage-6-trade-scheduling](stages/stage-6-trade-scheduling.md) - current to target at minimal cost, full telemetry
- Component 7 - Risk overlay and monitoring: [stage-7-risk-overlay-monitoring](stages/stage-7-risk-overlay-monitoring.md) - immune system; feedback into Components 1 and 2

## 3. Concept map by domain

Mining hub [stage-0-alpha-mining](stages/stage-0-alpha-mining.md): [formulaic-alpha-and-seeds](concepts/mining/formulaic-alpha-and-seeds.md), [ic-metrics-and-horizon-ladder](concepts/mining/ic-metrics-and-horizon-ladder.md), [ga-machinery](concepts/mining/ga-machinery.md), [alpha-generation-methods](concepts/mining/alpha-generation-methods.md)

Simulation hub [stage-1-canonical-simulation](stages/stage-1-canonical-simulation.md): [canonical-mapping](concepts/simulation/canonical-mapping.md), [canonical-pnl](concepts/simulation/canonical-pnl.md), [no-trade-band](concepts/simulation/no-trade-band.md), [harness-parameters](concepts/simulation/harness-parameters.md)

Evaluation hub [stage-2-evaluation-screening](stages/stage-2-evaluation-screening.md): [trial-count-and-thresholds](concepts/evaluation/trial-count-and-thresholds.md), [spec-sheet-and-monitoring](concepts/evaluation/spec-sheet-and-monitoring.md), [post-mortem](concepts/evaluation/post-mortem.md)

Pool and combination hubs [stage-3-orthogonalization](stages/stage-3-orthogonalization.md), [stage-4-combination](stages/stage-4-combination.md): [weighting-ladder](concepts/combination/weighting-ladder.md), [china-two-layer-architecture](concepts/combination/china-two-layer-architecture.md), [adaptive-weighting](concepts/combination/adaptive-weighting.md), [supplementary-techniques](concepts/combination/supplementary-techniques.md), [drawdown-overlay](concepts/combination/drawdown-overlay.md), [allocation-taxonomy](concepts/combination/allocation-taxonomy.md), [meta-labeling](concepts/combination/meta-labeling.md)

Sizing hub [stage-5-position-construction](stages/stage-5-position-construction.md): [position-sizing-methods](concepts/sizing/position-sizing-methods.md), [vol-targeting](concepts/sizing/vol-targeting.md), [leverage-cap](concepts/sizing/leverage-cap.md), [china-sizing-stack](concepts/sizing/china-sizing-stack.md), [scaling-layer-separation](concepts/sizing/scaling-layer-separation.md)

Execution hub [stage-6-trade-scheduling](stages/stage-6-trade-scheduling.md): [urgency-and-execution-algorithms](concepts/execution/urgency-and-execution-algorithms.md), [order-state-machine](concepts/execution/order-state-machine.md)

Risk hub [stage-7-risk-overlay-monitoring](stages/stage-7-risk-overlay-monitoring.md): [defense-layers](concepts/risk/defense-layers.md), [divergence-monitoring](concepts/risk/divergence-monitoring.md)

## 4. Case studies

[seed-alpha-demo](case-studies/seed-alpha-demo.md) - two seeds through the canonical harness on synthetic OHLCV plus book-depth data; script at research/seed_alpha_demo.py.

## 5. Reference

[glossary](glossary.md) - abbreviation expansions, stable English terms, terminology distinctions. [framework-lifecycle](framework-lifecycle.md) - build phases, runtime loop, operating cadence. templates/note-template.md - skeleton for new notes.

## 6. Standing decisions from the discussion

6.1 Data layer assumed ready: continuous series with rollover handled; out of scope.

6.2 Research phase uses fixed notional without compounding.

6.3 Target market VN30F1M intraday first; BTC perpetual later through venue-agnostic strategy and gateway separation.

6.4 Recommended adoption order lives in [supplementary-techniques](concepts/combination/supplementary-techniques.md) and [china-sizing-stack](concepts/sizing/china-sizing-stack.md).

6.5 Vietnamese conversation used may-tao register with English terms preserved; documents follow [style-guide](style-guide.md) in English.
