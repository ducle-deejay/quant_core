---
doc_id: CON-EV-TRIALS-THRESHOLDS
title: Trial Count and Threshold Calibration
type: specification
owner: research
status: approved
version: 1.1
components: [2]
tags: [evaluation, multiple-testing]
aliases: ["Trial Count", "Effective N", "Deflated Sharpe"]
source: "follow-up discussions: trial-count mechanics; threshold calibration sources"
---

# Trial Count and Threshold Calibration

## 1. Summary

One trial equals one chance given to randomness to look good on this data. The pass threshold is not fixed - it rises with effective trial count, set by the maximum of academic deflation, an empirical null run through your own harness, and operational economics.

## 2. What counts as one trial

A unique expression-plus-parameter-set evaluation whose result can influence a select or reject decision.

```text
    one formula x one parameter set                      counts as 1
    sweep of 100 parameter sets                          counts as 100, never 1
    rerun after changing cost model (influences call)    plus 1
    each GA individual per generation                    1 each
    infra rerun with byte-identical output               0
    post-admission monitoring vs pre-registered criteria 0
```


Counting spans every phase where data informs selection - mining fitness, screening, walk-forward - failures included. Implementation: every evaluation logs a hash of code version, params, and data range into the registry; duplicates dedupe by hash.

Raw N overcounts because GA output correlates heavily. Effective N comes from clustering survivors by PnL correlation (cut near 0.7) and counting clusters, or from the participation ratio of the trial-correlation eigenvalues: N_eff = (sum lambda)^2 / sum(lambda^2). Some shops skip explicit N and permutation- test each batch instead.

## 3. Where thresholds come from

Three combined sources. Academic anchors: Deflated Sharpe Ratio keeps the probability that best-of-N Sharpe is spurious below five percent; Harvey-Liu t-statistic haircuts; PBO/CSCV. Empirical null on your own harness - most important in factories: shuffle signals thousands of times through the exact z-to-band-to-cap-to-cost pipeline and take the ninety-fifth percentile of that null as the bar; it absorbs every pipeline quirk formulas cannot see, which is why Stage 1 must exist before thresholds do. Operational economics: minimum return worth a slot's attention; institutional standards emerge from survivor base rates.

Combination rule: only the primary statistic (walk-forward net Sharpe) receives deflation via max of the three sources. Secondary metrics - ICIR, decay, turnover, drag - are fixed engineering constraints, not inferred statistics.

---
## Links
- Up: [[stages/stage-2-evaluation-screening.md]]
- Related: [[stages/stage-0-alpha-mining.md]], [[concepts/mining/ic-metrics-and-horizon-ladder.md]]
