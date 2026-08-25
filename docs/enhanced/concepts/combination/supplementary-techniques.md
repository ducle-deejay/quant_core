---
doc_id: CON-CB-SUPPLEMENTARY
title: Supplementary Combination Techniques
type: specification
owner: research
status: approved
version: 1.1
components: [4]
tags: [combination, intraday]
aliases: ["Rank Normalization", "Regime Budgets", "Style Rotation", "Time-of-Day Weights", "Veto Gates", "End-to-End Optimizer"]
source: "follow-up discussion: five supplementary combination techniques"
---

# Supplementary Combination Techniques

## 1. Summary

Five techniques beyond the standard ladder, ordered by how soon they earn their keep in this project.

## 2. Specification

2.1 Rank or percentile score normalization. Map each alpha's score through its own empirical distribution before weighted summing. Kills fat-tail dominance: a twelve-sigma outlier cannot rule the composite just because its native scale is dirty. Near-zero cost; present in almost every real factory despite being absent from blogs. Adopt from day one.

2.2 Regime-conditioned risk budgets (style rotation). Preset budget vectors switch on measurable regime indicators such as volatility level or efficiency ratio. Rules for survival: at most three regimes; every preset walk-forward validated; transitions carry hysteresis - mandatory when regimes flip session-to-session on VN30F1M.

2.3 Time-of-day conditional weights. Session split into three to five buckets (open, mid-morning, post-lunch, pre-close); each bucket owns a frozen weight vector estimated from data. Microstructure alphas are strong at open and close, weak midday - one static vector across a day forces every segment to share one solution. A lookup table backed by statistics, no ML involved.

2.4 Veto and filter layers. Some alphas multiply instead of add: composite_position = base_allocation times the product of gates, gates in {0, 0.5, 1}. Example: a book-depth alpha does not forecast direction - it says depth is abnormally thin, halve exposure. Environment-condition signals wasted when added linearly should gate instead.

2.5 End-to-end optimizer (the Stage 4 to Stage 5 boundary). One optimizer takes all scores and outputs target positions directly with costs inside the objective: maximize expected return times position minus lambda times absolute position change, under caps. Grounded in Garleanu-Pedersen dynamic trading under transaction costs: optimal position is a weighted average of current and target positions, coefficient governed by cost over signal strength. Later-stage only - after the pool stabilizes and the cost model earns calibration from live fills.

Adoption order: now, items 1 plus inverse-vol plus equal-weight blend plus item 4 gates; pool grows, add item 3 tables plus rolling-IC adaptivity; multiple families, add item 2 budgets plus drawdown overlay; much later, item 5.

---
## Links
- Up: [stage-4-combination](../../stages/stage-4-combination.md), [stage-5-position-construction](../../stages/stage-5-position-construction.md)
- Related: [china-two-layer-architecture](china-two-layer-architecture.md), [adaptive-weighting](adaptive-weighting.md), [drawdown-overlay](drawdown-overlay.md)
