---
doc_id: CON-EV-POST-MORTEM
title: Post-Mortem
type: specification
owner: research
status: approved
version: 1.1
components: [2]
tags: [evaluation, process]
source: "follow-up discussion: post-mortem explanation and example"
---

# Post-Mortem

## 1. Summary

When an alpha dies, dissect the death to upgrade the factory - never to resurrect
the alpha. Every corpse is one iteration of the conveyor belt.

## 2. Specification

2.1 The two halves of the rule. The alpha stays dead; kill criteria were pre-
committed precisely so revivals require a full pipeline re-entry. The autopsy asks
one question only: why did it look good at test time.

2.2 Worked example. Seed A killed by its pre-registered rule at week nine produced
three findings. Regime frequency skew: forty percent of backtest sample sat in low-
volatility trending conditions, its habitat, while live reality supplied about ten
percent - lesson, add a gate that IC must be positive in every regime slice. Cost
model missed a dimension: afternoon-session depth thins and spreads widen, so the
flat buffer was wrong - lesson, cost models need time-of-day structure. Family
prior downgraded for all future members.

2.3 Outputs. Three pipeline patches - new regime gate, structured cost model,
updated prior - never a resurrected strategy. Requirements: interventions and
findings logged immutably; findings routed to the stage owning the flaw; kill
remains irreversible outside formal full-pipeline re-admission.

---
## Links
- Up: [[stages/stage-2-evaluation-screening.md]]
- Related: [[concepts/evaluation/spec-sheet-and-monitoring.md]], [[concepts/risk/divergence-monitoring.md]]
