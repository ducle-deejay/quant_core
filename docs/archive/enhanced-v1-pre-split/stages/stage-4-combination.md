---
doc_id: STG-4-COMBINATION
title: Component 4 - Combination
type: specification
owner: research
status: approved
version: 2.0
components: [4]
tags: [combination, stage-hub]
source: "docs/original/pipeline_stages/04_combination.md + follow-up discussions (China architecture, supplementary techniques, gamma/theta, allocation taxonomy). Reformatted per REF-STYLE."
---

# 4. Combination

## 1. Summary

Component 4 answers the final question of the score world: given k proven,
mutually incremental alphas, how do we combine them into a single forecast. From
here the system carries exactly one number per bar: the composite score.

## 2. Component contract

    INPUT : standardized score series + residual PnL series (Stage 3 dossiers)
            for every alpha in the pool
    OUTPUT: composite_score(t) = sum over i of w(i) * score_i(t)
            - one continuous series, fed to Component 5

Weights apply to standardized scores, so w(i) is purely a risk-budget allocation,
undistorted by each alpha's native scale.

## 3. Specification - the method ladder

3.1 Level 0, equal weight (1/k). The benchmark every level must beat
out-of-sample; DeMiguel and coauthors show 1/k is brutally hard to beat because
every fancier method pays for complexity in estimation error.

3.2 Level 1, inverse volatility. w(i) proportional to 1/vol(i); needs only
volatility estimates, hence robust. Default for small time-series pools.

3.3 Level 2, risk parity. Equalizes risk contributions using volatilities plus
the correlation matrix; still requires no expected-return forecast.

3.4 Level 3, mean-variance optimization. Adds expected returns - the weakest
link. Mandatory discipline: optimize on residual PnL (raw PnL funds duplicated
bets twice); apply shrinkage toward central tendency; include turnover penalty
lambda times abs of weight change; refit monthly or quarterly, never daily;
constrain weights non-negative, summing to one, with per-alpha caps around 25
percent.

3.5 Level 4, ML stacking (gradient boosting). Standard cross-sectional practice
with thousands of factors and huge samples. For one-instrument intraday pools the
effective sample is too small and nonlinear models learn noise. Requires all of:
hundreds of diverse factors, years of data, strict walk-forward validation.

## 4. Worked example

Pool: A1 morning momentum (daily vol 0.20%), A2 opening-range mean-reversion
(0.15%), C book-imbalance continuation (0.18%); pairwise correlations small or
negative.

    equal weight            weights 33/33/33   composite Sharpe 1.55
    inverse volatility      weights 29/39/32   composite Sharpe 1.68
    mean-variance, shrunk   weights 35/38/27   composite Sharpe 1.74
    naive mean-variance     weights 58/12/30   composite Sharpe 1.31 (loses)

Method complexity only pays when it controls estimation error; the naive
optimizer placed 58 percent of capital where estimation error was largest.

## 5. Failure modes

5.1 Weight overfitting - the number-one trap; defend by shrinkage plus
walk-forward applied to the choice of method itself.
5.2 Forgetting the equal-weight benchmark - without a reigning champion you never
know whether you are good.
5.3 Weight jumps creating portfolio turnover - separate signal turnover from
weight turnover; penalize the second relentlessly.
5.4 Correlation drift across regimes without periodic refits.
5.5 Confusing composite score with position - scaling belongs to Component 5.

## 6. Production practice notes

The full production picture - Chinese two-layer family architecture, adaptive
rolling-IC weighting with its two dials, drawdown overlays, five supplementary
techniques, alternative allocation algorithms, and meta-labeling placement - is
specified in dedicated notes:

[[concepts/combination/weighting-ladder.md]] (ladder details), [[concepts/combination/china-two-layer-architecture.md]],
[[concepts/combination/adaptive-weighting.md]], [[concepts/combination/supplementary-techniques.md]], [[concepts/combination/drawdown-overlay.md]],
[[concepts/combination/allocation-taxonomy.md]], [[concepts/combination/meta-labeling.md]].

---
## Related notes
- [[stages/stage-3-orthogonalization.md]], [[stages/stage-5-position-construction.md]]
- All seven combination concept notes listed in section 6
