---
doc_id: REF-GLOSSARY
title: Glossary and Terminology Conventions
type: reference
owner: research
status: approved
version: 1.1
components: []
tags: [glossary, conventions]
source: "discussion conventions"
---

# Glossary and Terminology Conventions

## 1. Abbreviations used earlier, expanded form is standard

Sharpe ratio (was SR). Information Coefficient, correlation between forecast and
forward return (was IC). ICIR - Sharpe ratio computed on the time series of
Information Coefficients. Maximum drawdown (was MDD). In-sample and out-of-sample
(were IS and OOS). Genetic algorithm (was GA). Exponentially weighted moving
average (was EWMA). Deflated Sharpe ratio (was DSR). PnL stays as-is - profit and
loss, a proper noun in practice. DSL - domain-specific language.

## 2. Stable English terms never translated in Vietnamese discussion

alpha, score, signal, backtest, live, fill, order book, depth, imbalance, spread,
slippage, turnover, drawdown, regime, walk-forward, in-sample, out-of-sample, risk
budget, vol targeting, kill switch, weighting scheme, orthogonalization,
composite, position, target position, execution, fill price, cost model, capacity,
crowding.

## 3. Notation standard

Registry: [[reference/notation.md]]. Style rules: [[style-guide.md]] section 4. p(t), z(t), r(t), c, L, vol_target, vol_est(t),
TO(t), IC(h), h_star, N_eff, w(i), m.

## 4. Terminology distinctions worth remembering

Formulaic alpha versus weighting scheme or allocation algorithm: the former lives
at Component 0 (DSL expressions generating scores); the latter lives at Component 4
(how weights are assigned). Never use loose "formula" for the latter.

Signal or forecast versus exposure or position: forecasts are dimensionless; money
exists only after Component 5 converts forecast into position. Position sizing is
that conversion, portfolio level only.

Notional exposure (p times capital) versus risk exposure (p times capital times
estimated volatility): vol targeting manages the second through the first.

Search fitness (mining selection pressure) versus acceptance criteria (formal
Stage 2 gates): same tools, different roles.

Component versus build phase versus runtime loop: see [[framework-lifecycle.md]].

---
## Related notes
- [[HOME.md]], [[style-guide.md]], [[framework-lifecycle.md]]
