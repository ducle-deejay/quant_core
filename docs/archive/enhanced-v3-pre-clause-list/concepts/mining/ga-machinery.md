---
doc_id: CON-MIN-GA-MACHINERY
title: GA Mining Machinery
type: specification
owner: research
status: approved
version: 1.1
components: [0]
tags: [mining, genetic-algorithm, fitness]
source: "discussion: GA fitness composition; search vs acceptance roles"
---

# GA Mining Machinery

## 1. Summary

Genetic algorithms are one of three idea generators (with grammar enumeration and human seeds). Their fitness function is the selection pressure: design it as one primary objective plus hard constraints, or the machine optimizes self-deception.

## 2. Specification

2.1 Three generator families run in production: brute-force grammar enumeration; genetic programming (crossover and mutation on expression trees); hand-written human seeds. Firms run mixtures - GA without quality seeds breeds garbage, and selection pressure lives in fitness, not crossover.

2.2 Fitness designs. Scalarized composite, WorldQuant form:

```text
    fitness = ICIR * sqrt(abs(R_ann)) / max(TO, TO_floor)
    fitness   selection-pressure score for a candidate alpha
    ICIR      Sharpe ratio on the alpha's IC time series
              ([[concepts/mining/ic-metrics-and-horizon-ladder.md]])
    R_ann     annualized return of the canonical PnL
    TO        annualized turnover, multiples of capital per year
    TO_floor  0.125 floor against division blowup; WorldQuant convention
```


multiplicative so any zero component kills the candidate. Single objective plus hard constraint filters - cleanest, no cross-objective tuning. True multi- objective Pareto fronts (NSGA-II) - expensive; downstream picks from the front.

2.3 Two laws. The GA exploits every loophole in its fitness function (Goodhart's law); linear weighted sums are most exploitable. Each weighted component flattens selection pressure and adds an overfitting degree of freedom to the search itself.

2.4 Role separation. Search fitness steers mining only; formal pass/fail happens at Stage 2 with canonical-PnL Sharpe, walk-forward, deflated thresholds. Results of the former are never conclusions of the latter.

Survivor organization continues in [[stages/stage-0-alpha-mining.md]], section 7.

---
## Related notes
- Up: [[stages/stage-0-alpha-mining.md]]
- Related: [[concepts/mining/formulaic-alpha-and-seeds.md]], [[concepts/evaluation/trial-count-and-thresholds.md]]
