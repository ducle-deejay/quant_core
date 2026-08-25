---
doc_id: STG-2-EVALUATION
title: Component 2 - Evaluation and Screening
type: specification
owner: research
status: approved
version: 2.0
components: [2]
tags: [evaluation, stage-hub]
source: "docs/original/pipeline_stages/02_evaluation_screening.md + follow-up discussions. Reformatted per REF-STYLE."
---

# 2. Evaluation and Screening

## 1. Component contract

    INPUT : Stage 1 dossier (daily gross/net PnL, turnover, cost drag,
            score series)
    OUTPUT: IN/OUT decision; on PASS a complete spec sheet; on FAIL a logged
            rejection reason in the registry

## 2. Summary

Component 2 grades the dossier each candidate carries out of Component 1 and
decides admission to the pool. It answers three questions in order: is the
information real, does it survive costs, is the result stable across time and
across the number of trials performed. Only three-yes candidates proceed.

## 3. Specification

3.1 Full metric suite. Forecast layer: Rank IC at the horizon ladder {1, 5, 15,
...} with block t-statistics, ICIR, decay profile - "is it information or noise,
and how long does it live". Economics layer: net Sharpe annualized, maximum
drawdown, turnover, cost drag as percentage of gross eaten by fees - "what
survives costs". Additionally inspect the distribution of daily PnL: skew, worst
days, long/short symmetry. An alpha earning from one side only is betting on one
regime, not holding an edge.

3.2 Temporal stability (walk-forward). Slice history into rolling blocks
(weekly/monthly for intraday VN30F1M). Require: positive IC/Sharpe in a majority
of blocks; bounded worst block; survival after removing the single best block;
documented habitat per regime slice (volatility level, session half,
trend/chop) - even for passing alphas.

3.3 Parameter plateau. Sweep alpha parameters on a grid around plus/minus thirty
percent of chosen values. Require a plateau: neighbors of the optimum perform
nearly as well. A sharp single-point peak is noise-fitting; reject regardless of
the peak's beauty.

3.4 Multiple-testing control. Every evaluation ever performed sits in a ledger.
The acceptance threshold rises with effective trial count within the strategy
family, following deflated-Sharpe logic: after five hundred trials, the best pure
garbage shows a respectable Sharpe by chance alone, so the bar sits above that
level. Cheapest task in the pipeline, most often skipped, decides whether the
factory is honest with itself.

3.5 Gate decision. All conditions must hold simultaneously:

    net Sharpe (walk-forward)   > deflated threshold given trial count [e.g., > 0.8]
    ICIR                        > 0.3
    decay                       > 0 through the target holding period
    cost drag                   < 40 percent of gross
    turnover                    < ceiling of the strategy slot
    parameter plateau           stable around the optimum
    positive blocks             > 60 percent

On PASS the alpha proceeds carrying a spec sheet: expected holding period,
expected net Sharpe, capacity estimate, regime dependence, live kill criteria
(example: rolling 20-day IC below zero for two consecutive weeks switches it
off). On FAIL the reason is logged into the registry - insurance against anyone
re-mining the same idea later under a new name.

## 4. Failure modes

4.1 Grading on the full sample instead of walk-forward - selection bias against
yourself.
4.2 Skipping the daily-PnL distribution check - one-sided earnings pass silently.
4.3 Fixed thresholds regardless of trial count - the factory starts believing
its own best-of-N luck.
4.4 Accepting sharp parameter peaks - noise promoted to production.

Detailed procedures live in dedicated notes:
[[concepts/evaluation/trial-count-and-thresholds.md]] (what counts as one trial, effective N, the three
threshold sources), [[concepts/evaluation/spec-sheet-and-monitoring.md]] (spec purposes, holding-period
estimation from two views, expected-Sharpe shrinkage, divergence reading),
[[concepts/evaluation/post-mortem.md]] (dissection discipline), [[concepts/mining/ic-metrics-and-horizon-ladder.md]]
(measurement mechanics).

---
## Related notes
- [[stages/stage-1-canonical-simulation.md]], [[stages/stage-3-orthogonalization.md]]
- [[concepts/evaluation/trial-count-and-thresholds.md]] - trial accounting and the three threshold sources
- [[concepts/evaluation/spec-sheet-and-monitoring.md]], [[concepts/evaluation/post-mortem.md]]
