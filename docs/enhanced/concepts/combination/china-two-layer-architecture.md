---
doc_id: CON-CB-CHINA-TWO-LAYER
title: China Two-Layer Combination Architecture
type: specification
owner: research
status: approved
version: 1.1
components: [4]
tags: [combination, governance]
aliases: ["Sub-Portfolio", "Strategic Risk Budget", "Style Rotation"]
source: "follow-up discussions: real Chinese production practice for combination"
---

# China Two-Layer Combination Architecture

## 1. Summary

Chinese shops do not run one big optimizer over the pool. Alphas group into strategy families running as independent sub-portfolios, and a quarterly-governed strategic risk budget allocates across families. The edge is governance discipline, not weight mathematics.

## 2. Specification

2.1 Layer one, sub-portfolios by strategy family (short-term momentum, mean-reversion, market microstructure, session seasonality). Each family runs vol targeting internally. Intra-family correlations reach 0.7 to 0.9 where any optimization is unstable, so combination stays deliberately crude: sum of standardized scores or inverse-volatility weights.

2.2 Layer two, strategic risk budget across families - for example momentum 35 percent, mean-reversion 30, microstructure 25, seasonality 10. Budget means share of total composite variance each family may contribute. Reviewed quarterly by a process with humans in it, backed by walk-forward and live evidence. Changes slowly because it reflects evidence about which edge sources remain alive.

2.3 Extensions layered on top: regime-conditioned budget presets with hysteresis (style rotation), time-of-day weight tables, drawdown multipliers owned by an independent risk team.

2.4 Why this dominates despite flat mean-variance being theoretically superior under known covariance: error tolerance. Hierarchical decisions degrade gracefully under noisy inputs, stay auditable, map to organizational ownership. Foundation: DeMiguel's result that equal weight beats optimized portfolios out-of-sample; hierarchies scale that insight to alpha pools. When families lack obvious semantics, Hierarchical Risk Parity automates the clustering-plus-allocation tree.

---
## Links
- Up: [stage-4-combination](../../stages/stage-4-combination.md)
- Related: [weighting-ladder](weighting-ladder.md), [adaptive-weighting](adaptive-weighting.md), [drawdown-overlay](drawdown-overlay.md), [allocation-taxonomy](allocation-taxonomy.md), [supplementary-techniques](supplementary-techniques.md)
