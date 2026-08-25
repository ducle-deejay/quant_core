---
doc_id: CON-CB-ADAPTIVE-WEIGHTING
title: Adaptive Weighting (Rolling IC and Max-IC)
type: specification
owner: research
status: approved
version: 1.1
components: [4]
tags: [combination, adaptive-weighting]
aliases: ["Rolling IC Weighting", "Max Composite IC", "Gamma Theta"]
source: "follow-up discussions: rolling-IC weighting details; max-composite-IC regression"
---

# Adaptive Weighting

## 1. Summary

Two production-grade adaptive schemes. Both avoid absolute expected-return estimates - the weakest input of mean-variance.

## 2. Rolling-IC weighting

2.1 Formula:

```text
    w(i) proportional to max(rolling_IC(i), 0) ^ gamma
    w_final = theta * w_IC + (1 - theta) * w_equal
    rolling_IC(i)  recent-window Information Coefficient of alpha i
    gamma          concentration exponent (practical range 1-2)
    theta          trust dial toward equal weight (range 0.3-0.5)
    w_IC           weight vector proportional to rolling IC
    w_equal        equal-weight vector 1/n_alpha
    refit cadence: weekly or monthly (see section 2 text)
```

2.2 The two dials. gamma is the concentration dial: how hard winners differentiate. At gamma = 1 an IC of 0.06 versus 0.03 earns twice the weight; at gamma = 2, four times. Above about two you chase IC estimation noise - alphas with true ICs 0.04 and 0.05 swap ranks every window and squaring amplifies that noise. theta is the trust dial: partial trust in recent measurement buys large variance reduction with small bias, and stops the layer chasing recent luck. Both knobs are governance parameters swept on train data, owned by no individual alpha.

## 3. Max-composite-IC weighting

Choose weights maximizing the correlation between the weighted score sum and forward return - a linear regression of forward returns on scores with non-negativity constraints and ridge regularization. Optimal weights are regression coefficients. Run on rolling windows applied out-of-sample, then average the weight vectors across windows. Needs only forecast structure, which IC measures directly - no absolute return estimates.

Both schemes embody Stage 4's philosophy: slow adaptation shrunk toward an anchor, auditable at every step.

---
## Links
- Up: [stage-4-combination](../../stages/stage-4-combination.md)
- Related: [china-two-layer-architecture](china-two-layer-architecture.md), [weighting-ladder](weighting-ladder.md), [allocation-taxonomy](allocation-taxonomy.md)
