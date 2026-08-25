---
doc_id: CON-CB-WEIGHTING-LADDER
title: Weighting Scheme Ladder
type: specification
owner: research
status: approved
version: 1.1
components: [4]
tags: [combination, weighting]
aliases: ["Equal Weight Benchmark", "Mean-Variance"]
source: "original stage-4 ladder section"
---

# Weighting Scheme Ladder

## 1. Summary

Five levels from equal weight to ML stacking. Complexity pays only when it
controls estimation error; equal weight is the reigning benchmark every level must
beat out-of-sample.

## 2. Specification

2.1 Level 0, equal weight (1/k). Mandatory benchmark; DeMiguel and coauthors show
it is brutally hard to beat because fancier methods pay in estimation error.

2.2 Level 1, inverse volatility. w(i) proportional to 1 over each alpha's PnL
volatility; needs only volatility estimates, hence robust. Default for small
time-series pools.

2.3 Level 2, risk parity. Equalizes risk contributions using volatilities plus the
correlation matrix; no expected-return forecast required.

2.4 Level 3, mean-variance optimization. Adds expected returns - the weakest link.
Mandatory discipline: optimize on residual PnL from Stage 3 dossiers (raw PnL funds
duplicated bets twice); shrinkage toward central tendency; turnover penalty lambda
times abs of weight change; refit monthly or quarterly never daily; weights non-
negative summing to one with per-alpha caps around twenty-five percent.

2.5 Level 4, ML stacking (gradient boosting). Standard cross-sectional practice.
For one-instrument intraday pools the effective sample is too small - nonlinear
models learn noise. Requires all three: hundreds of diverse factors, years of data,
strict walk-forward validation.

2.6 Worked comparison for pool A1/A2/C: equal weight Sharpe 1.55; inverse
volatility 1.68; disciplined mean-variance 1.74; naive mean-variance 1.31. The
naive optimizer loses to equal weight by placing fifty-eight percent of capital
where estimation error was largest.

2.7 Traps. Weight overfitting first; forgetting the benchmark; weight jumps
creating portfolio turnover; correlation drift without refits; confusing composite
score with position.

---
## Links
- Up: [[stages/stage-4-combination.md]]
- Related: [[concepts/combination/china-two-layer-architecture.md]], [[concepts/combination/adaptive-weighting.md]],
  [[concepts/combination/allocation-taxonomy.md]]
