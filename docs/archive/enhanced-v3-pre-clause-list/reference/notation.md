---
doc_id: REF-NOTATION
title: Notation Registry
type: reference
owner: research
status: approved
version: 1.0
components: []
tags: [notation, registry]
source: "extracted from style-guide section 4; conflicts resolved per Rules A-C"
---

# Notation Registry

Single source of truth for every symbol used in formulas across this vault.

```text
    Rule A   one symbol, one meaning vault-wide
    Rule B   local reuse of a symbol for a different sense requires an inline
             declaration at first use ("here X denotes ...")
    Rule C   a symbol appearing in a formula must exist in this registry, or be
             added to it in the same change
```


## 1. Position and return quantities

```text
    p(t)         position at bar t, in multiples of capital notional
                 (fixed-notional convention; introduced in Component 1)
    r(t)         asset return over bar t
    z(t)         standardized score at bar t, in standard deviations from own
                 rolling history (produced by the Component 1 mapping)
```


## 2. Volatility and sizing

```text
    vol_target   declared volatility target, converted to bar frequency
    vol_est(t)   estimated volatility at bar t (short/long EWMA blend or
                 realized high-frequency estimate; floor applied)
    L            leverage cap policy, in multiples of capital
    m            de-risking multiplier in [0, 1]; prefixed variants
                 (m_drawdown, m_regime, m_meta, m_rampup) share this base
                 meaning - see [[concepts/combination/drawdown-overlay.md]],
                 [[concepts/sizing/china-sizing-stack.md]],
                 [[concepts/combination/meta-labeling.md]]
```


## 3. Costs and turnover

```text
    c            cost per unit notional per side = fee + half-spread [+ buffer];
                 VN30F1M working number about 0.5 bp per side
    TO(t)        one-way turnover at bar t = abs(p(t) - p(t-1)), in multiples
                 of capital
    TO_floor     turnover floor constant 0.125 used in the WorldQuant-style
                 fitness denominator (source: "101 Formulaic Alphas")
```


## 4. Forecast quality

```text
    IC(h)        Information Coefficient at horizon h: correlation between
                 score at t and cumulative forward return over h bars
    ICIR         Sharpe ratio computed on the time series of IC values
    R_ann        annualized return of a candidate's canonical PnL
    h_star       estimated holding period
    N_eff        effective number of independent trials
                 N_eff = (sum lambda)^2 / sum(lambda^2) on trial-PnL
                 correlations
```


## 5. Weights and combination

```text
    w(i)         combination weight of alpha i; pool size denoted n_alpha
    gamma        concentration exponent in rolling-IC weighting (practical
                 range 1-2)
    theta        blend weight toward equal weight (practical range 0.3-0.5)
    lambda_w     turnover-penalty coefficient in the mean-variance objective
                 (Component 4 discipline rule)
```


## 6. Smoothing and search

```text
    lambda_s     EWMA smoothing weight (Component 1 step A);
                 lambda_s = 2 / (span + 1)
    n_trials     raw count of logged evaluation events in the trial ledger
```


## 7. Conflict resolutions applied

Former bare lambda was ambiguous between the EWMA weight and the turnover penalty; split into lambda_s and lambda_w. Former bare k as a pool-size counter is renamed n_alpha; k stays reserved as a local, declared-at-use-site name (for example seed grammar window lengths).

---
## Related notes
- [[style-guide.md]] - presentation rules for formula blocks
- [[concepts/mining/ic-metrics-and-horizon-ladder.md]] - IC family detail
