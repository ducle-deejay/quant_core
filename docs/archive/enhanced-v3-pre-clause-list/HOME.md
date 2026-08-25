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

Second-brain vault for the systematic trading pipeline designed for VN30F1M intraday, extensible to BTC perpetual. Frozen first-presentation documents live in docs/original/pipeline_stages. This vault integrates every follow-up discussion in shop-standard format defined by [[style-guide.md]].

## 1. How to navigate

1.1 Humans start at the component list below and follow path-style wikilinks ([[stages/stage-6-trade-scheduling.md]] form). Vault must be rooted at docs/enhanced (or a parent) for resolution.

1.2 Agents rely on predictable paths (stages, concepts by domain), YAML front matter with doc_id and components, and plain-markdown basenames as links - greppable without Obsidian.

1.3 One idea per concept note. Stage hubs hold flow plus verbatim core. Duplicates forbidden; link instead.

1.4 Preservation rule: originals are read-only. Corrections appear here as Clarification paragraphs pointing back to the original passage.

## 2. The eight components

- Component 0 - Alpha mining: [[stages/stage-0-alpha-mining.md]] - DSL grammar x seeds x GA -> thousands of stateless scores
- Component 1 - Canonical simulation: [[stages/stage-1-canonical-simulation.md]] - one uniform score-to-position mapping -> comparable net PnL dossier
- Component 2 - Evaluation and screening: [[stages/stage-2-evaluation-screening.md]] - gates: information, cost survival, stability, deflated thresholds
- Component 3 - Orthogonalization: [[stages/stage-3-orthogonalization.md]] - admit only incremental value versus the pool
- Component 4 - Combination: [[stages/stage-4-combination.md]] - residual dossiers -> composite score through governance
- Component 5 - Position construction: [[stages/stage-5-position-construction.md]] - vol targeting stack -> target position; risk begins here
- Component 6 - Trade scheduling: [[stages/stage-6-trade-scheduling.md]] - current to target at minimal cost, full telemetry
- Component 7 - Risk overlay and monitoring: [[stages/stage-7-risk-overlay-monitoring.md]] - immune system; feedback into Components 1 and 2

## 3. Concept map by domain

Mining ([[stages/stage-0-alpha-mining.md]]): [[concepts/mining/formulaic-alpha-and-seeds.md]], [[concepts/mining/ic-metrics-and-horizon-ladder.md]], [[concepts/mining/ga-machinery.md]], [[concepts/mining/alpha-generation-methods.md]]

Simulation ([[stages/stage-1-canonical-simulation.md]]): [[concepts/simulation/canonical-mapping.md]], [[concepts/simulation/canonical-pnl.md]], [[concepts/simulation/no-trade-band.md]], [[concepts/simulation/harness-parameters.md]]

Evaluation ([[stages/stage-2-evaluation-screening.md]]): [[concepts/evaluation/trial-count-and-thresholds.md]], [[concepts/evaluation/spec-sheet-and-monitoring.md]], [[concepts/evaluation/post-mortem.md]]

Pool and combination ([[stages/stage-3-orthogonalization.md]], [[stages/stage-4-combination.md]]): [[concepts/combination/weighting-ladder.md]], [[concepts/combination/china-two-layer-architecture.md]], [[concepts/combination/adaptive-weighting.md]], [[concepts/combination/supplementary-techniques.md]], [[concepts/combination/drawdown-overlay.md]], [[concepts/combination/allocation-taxonomy.md]], [[concepts/combination/meta-labeling.md]]

Sizing ([[stages/stage-5-position-construction.md]]): [[concepts/sizing/position-sizing-methods.md]], [[concepts/sizing/vol-targeting.md]], [[concepts/sizing/leverage-cap.md]], [[concepts/sizing/china-sizing-stack.md]], [[concepts/sizing/scaling-layer-separation.md]]

Execution ([[stages/stage-6-trade-scheduling.md]]): [[concepts/execution/urgency-and-execution-algorithms.md]], [[concepts/execution/order-state-machine.md]]

Risk ([[stages/stage-7-risk-overlay-monitoring.md]]): [[concepts/risk/defense-layers.md]], [[concepts/risk/divergence-monitoring.md]]

## 4. Case studies

[[case-studies/seed-alpha-demo.md]] - two seeds through the canonical harness on synthetic OHLCV plus book-depth data; script at research/seed_alpha_demo.py.

## 5. Reference

[[glossary.md]] - abbreviation expansions, stable English terms, terminology distinctions. [[framework-lifecycle.md]] - build phases, runtime loop, operating cadence. templates/note-template.md - skeleton for new notes.

## 6. Standing decisions from the discussion

6.1 Data layer assumed ready: continuous series with rollover handled; out of scope.

6.2 Research phase uses fixed notional without compounding.

6.3 Target market VN30F1M intraday first; BTC perpetual later through venue- agnostic strategy and gateway separation.

6.4 Recommended adoption order lives in [[concepts/combination/supplementary-techniques.md]] and [[concepts/sizing/china-sizing-stack.md]].

6.5 Vietnamese conversation used may-tao register with English terms preserved; documents follow [[style-guide.md]] in English.
