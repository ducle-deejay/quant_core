---
doc_id: STG-3-ORTHOGONALIZATION
title: Component 3 - Orthogonalization (Pool Admission)
type: specification
owner: research
status: approved
version: 2.0
components: [3]
tags: [pool, stage-hub]
source: "docs/original/pipeline_stages/03_orthogonalization.md (no follow-up Q&A occurred). Reformatted per REF-STYLE."
---

# Component 3 - Orthogonalization (Pool Admission)

## 1. Component contract

```text
    INPUT : candidate daily net PnL stream
            plus daily net PnL streams of pool members
            (or of the composite portfolio under current weights - stricter)
    OUTPUT: IN/OUT decision; for admitted alphas, a residual dossier stored in
            the registry (residual series, residual Sharpe, beta vector)
```

## 2. Summary

Component 3 answers exactly one question: does this alpha bring anything the pool does not already have. The answer comes from a regression against the pool's PnL, never from impressions or pairwise correlation cutoffs.

Measured on PnL, not signal values - what the pool needs independence from is cash flow, not series shapes.

## 3. Specification

3.1 Regression form:

```text
    pnl_candidate(t) = alpha
                       + beta_1 * pnl_pool_1(t)
                       + ...
                       + beta_k * pnl_pool_k(t)
                       + epsilon(t)
    alpha       intercept; absorbed by walk-forward grading
    beta_i      exposure of candidate PnL to pool member i
    epsilon(t)  residual = pure incremental value, graded on test blocks
```

The explained part (beta terms) is duplication; the residual epsilon is pure incremental value; the decision applies to epsilon only.

3.2 Pass bar, lower than Stage 2 because the role is supplementation:

```text
    Sharpe(residual) > 0.3 to 0.5   or   t-statistic(epsilon) > 2
```

estimated walk-forward: betas fit on train blocks, residual graded on test blocks.

3.3 Regressor choice. Prefer the composite portfolio under current weights over individual members - independence is required versus the portfolio actually running.

3.4 Stability controls. Large pools with short samples use ridge regularization or reduce regressors to principal components of the pool. Betas drift across regimes, so re-run quarterly and monitor rolling R-squared.

3.5 Small-but-stable residuals are acceptable if the t-statistic clears; small sure value still compounds at Stage 4.

## 4. Worked example

Pool holds A1 (morning momentum) and A2 (opening-range mean-reversion).

Candidate C, standalone Sharpe 1.10:

```text
    C = 0.02 + 0.45*A1 + 0.18*A2 + epsilon     R-squared = 0.31
    Sharpe(residual) = 0.82,  t = 2.6          PASS
```

Candidate D, standalone Sharpe 0.90:

```text
    D = 0.01 + 0.52*A1 + 0.35*A2 + epsilon     R-squared = 0.78
    Sharpe(residual) = 0.14,  t = 0.9          REJECT
```

D's highest pairwise correlation with any single member was 0.58 - below a 0.6 cutoff - so a pairwise filter would have admitted it wrongly. D duplicates no one individually; it duplicates the aggregate. This example is the entire reason the component exists.

## 5. Failure modes

5.1 The self-deception spiral: every admission makes the pool more explanatory, later residuals harder to clean; without logging and scheduled re-runs the pool fills artificially. Keep pool size controlled (tens to hundreds for time-series).

5.2 Overfitting betas then rewarding yourself with a fake-beautiful residual - prevented by the walk-forward split.

5.3 Weighting raw PnLs at Stage 4 instead of residual dossiers - funds duplicated bets twice.

One-sentence summary: Stage 2 asks whether this alpha is good; Stage 3 asks whether it is new; getting either wrong costs money all the same.

---
## Related notes
- [stage-2-evaluation-screening](stage-2-evaluation-screening.md), [stage-4-combination](stage-4-combination.md)
