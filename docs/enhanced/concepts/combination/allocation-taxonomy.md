---
doc_id: CON-CB-ALLOCATION-TAXONOMY
title: Allocation Algorithm Taxonomy
type: specification
owner: research
status: approved
version: 1.1
components: [4]
tags: [combination, allocation]
aliases: ["HRP", "Hierarchical Risk Parity", "Online Learning Allocation"]
source: "follow-up discussion: allocation algorithms beyond the ladder"
---

# Allocation Algorithm Taxonomy

## 1. Summary

Beyond the standard ladder, industry alternatives all sit on two axes - hierarchy first then optimization, and slow adaptation shrunk toward an anchor. Family architecture dominates production not by theoretical optimality but by tolerance to estimation error.

## 2. Catalog

2.1 Hierarchical Risk Parity (Lopez de Prado). Tree built from correlation distance; capital allocated by inverse variance down branches. Family weighting where the algorithm clusters automatically; no covariance inversion; tolerates hundreds of correlated members. Common above one hundred pool members; the bridge between flat optimization and manual families.

2.2 Cluster-then-budget fully automated. Correlation clustering, equal risk per cluster, optimize inside. Same philosophy when families lack obvious semantics.

2.3 Online learning allocation (multiplicative weights, Hedge-style). Weights updated online from realized performance with regret guarantees. Some systematic shops run it at sub-strategy level.

2.4 Kalman filter on Information Coefficient. Each alpha's true IC treated as hidden state; posterior updated daily; weight proportional to posterior mean, already shrunk. The educated version of rolling-IC weighting.

2.5 Black-Litterman-style blending. Family expectations as prior views updated by live evidence. Rarely used verbatim; conceptually what quarterly reviews are.

2.6 Forward-selection ensembling. Greedily add alphas, keep only out-of-sample improvements. Cross-sectional practice with thousands of factors.

2.7 Is family weighting best? For time-series futures production, yes - dominantly - but not theoretically. With known covariance, flat mean-variance wins. Family architecture wins out-of-sample through error tolerance: hierarchical decisions degrade gracefully, stay auditable, map to organizational ownership. Practical path here: inverse-vol plus equal-weight blend in one family now; past thirty alphas consider HRP to automate hierarchy instead of hand-labeling.

---
## Links
- Up: [stage-4-combination](../../stages/stage-4-combination.md)
- Related: [china-two-layer-architecture](china-two-layer-architecture.md), [weighting-ladder](weighting-ladder.md), [meta-labeling](meta-labeling.md)
