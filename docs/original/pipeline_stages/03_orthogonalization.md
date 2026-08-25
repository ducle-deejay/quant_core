# Stage 3 — Orthogonalization (Pool Admission)

> Provenance: faithful English rendering of the first full presentation of
> Stage 3. Follow-up Q&A is not included here.

Stage 3 answers exactly one question: *"Does this alpha bring anything the pool
does not already have?"* — and it answers with statistics, not impressions.

## The problem this stage solves

After Stage 2, the candidates are individually qualified. But **"strong on its
own" ≠ "valuable when standing together."** Two classic failure modes:

1. The new alpha earns from the **same risk source** as the pool (e.g., another
   slow momentum) — adding it raises portfolio Sharpe far less than expected;
2. Conversely, an alpha correlated 0.7 with one member may still have a strong
   enough residual — cutting by correlation threshold throws away good inventory.

The pairwise correlation cutoff (the old way) suffers both flaws: it cannot see
correlation with the **combination** of the pool, and it does not measure the
**magnitude of the independent part**. Orthogonalization fixes both with one
regression.

## Contract

```
INPUT : candidate's daily net PnL stream
      + daily net PnL streams of existing pool members
        (or of the composite portfolio under current weights — stricter)

OUTPUT: IN/OUT decision + residual dossier stored into the registry
```

Measured on **PnL, not signal values** — what the pool needs independence from
is cash flow, not series shapes.

## Mechanics — the regression says everything

```
pnl_candidate(t) = α + β₁·pnl_pool₁(t) + … + β_k·pnl_poolₖ(t) + ε(t)
                                                       └── residual
```

Reading each component:

- `Σβᵢ·pool` = everything the candidate earns that the pool can already
  **explain** — i.e., duplication;
- `ε` = what remains = the **pure incremental value**;
- The decision applies to the quality of `ε`, never to the candidate's raw stats.

The pass criterion applies to the residual with a threshold **lower** than
Stage 2's (its role is supplementation, not carrying the show):

```
PASS if:  Sharpe(residual) > ~0.3–0.5   or   t(ε) > 2
          (walk-forward, same anti-look-ahead principle:
           β estimated on train blocks, residual graded on test blocks)
```

## Worked example — and why the pairwise cutoff dies here

Pool holds two alphas: A1 (morning momentum), A2 (opening-range mean-reversion).
Two candidates arrive:

**Candidate C** (`book_imbalance_cont`, standalone Sharpe 1.10):

```
C = 0.02 + 0.45·A1 + 0.18·A2 + ε        R² = 0.31
Sharpe(residual) = 0.82,  t = 2.6  → PASS ✓
```

It shares quite a lot with A1 (β₁ = 0.45) but retains a strong cash flow of its
own — deserving a pool seat.

**Candidate D** (standalone Sharpe 0.90, looks fine):

```
D = 0.01 + 0.52·A1 + 0.35·A2 + ε        R² = 0.78
Sharpe(residual) = 0.14,  t = 0.9   → REJECT ✗
```

The expensive lesson in this example: D's highest pairwise correlation with any
single member was only **0.58 — below the 0.6 cutoff**, so the old filter would
have **admitted it wrongly**. D duplicates no one *individually*; it duplicates
the *aggregate* — and only regression against the combination catches that.
This is the entire reason Stage 3 exists.

## Technical decisions practitioners must pin down

| Issue | Standard practice | Why |
|---|---|---|
| Regress against members or composite? | Composite under current weights | What must stay independent is the *portfolio actually running*, not its pieces |
| Full sample or walk-forward? | β fit on train blocks, residual graded on test blocks | Prevents overfitting β then rewarding yourself a fake-beautiful residual |
| Large pool, short sample → noisy β | Ridge / regularization, or reduce regressors to principal components of the pool | k regressors × thin PnL matrix is the textbook overfit recipe |
| Betas drift across regimes | Re-run orthogonalization periodically (quarterly) + monitor rolling R² | Inter-alpha relationships are not static |
| Small but stable residual | Still acceptable if it clears the t-threshold | Small-but-sure value still compounds at Stage 4 |

## The trap to fear most: the self-deception spiral

Every admitted alpha makes the pool more explanatory → residuals of later
candidates get harder to clean. Without logging and disciplined re-runs, the
pool ends up artificially "full". Firms keep the pool at controlled size
(tens to hundreds for time-series; thousands for cross-sectional where ML
combination takes over).

## Handoff to Stage 4

Stage 3's output is not just IN/OUT — every surviving alpha carries a
**residual dossier**: the ε(t) series, residual Sharpe, beta vector. It is these
series that Stage 4 uses to allocate weights — never the raw PnLs (weighting on
the duplicated part means funding the same bet twice).

## One-sentence summary

Stage 2 asks *"is this alpha good?"*, Stage 3 asks *"is this alpha new?"* — two
independent questions, and getting either wrong costs money all the same.
