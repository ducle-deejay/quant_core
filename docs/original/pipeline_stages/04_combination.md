# Stage 4 — Combination

> Provenance: faithful English rendering of the first full presentation of
> Stage 4 (the technique ladder from equal weight to ML stacking). Follow-up
> discussions — the Chinese two-layer architecture, the five supplementary
> techniques, γ/θ mechanics, clustering at scale, alternative allocation
> algorithms, meta-labeling — are not included here.

Stage 4 answers the final question of the score world: *"I hold k alphas — how
do I combine them into a single forecast?"* From here on the system carries
exactly **one** number per bar: the composite score.

## The problem this stage solves

After Stage 3 the pool is a set of proven alphas. But one money decision remains
unsettled: **what share of the risk budget goes to each alpha?**

This is harder than it looks, because wrong weights wreck the work of three
stages in exactly two ways:

- Over-funding high-volatility alphas → the composite is dominated by one child,
  and diversification becomes decoration;
- Naive mean-variance optimization → noisy expected-return estimates push peak
  weight onto precisely the alpha with the *largest estimation error*
  (the classic error-maximization phenomenon).

## Contract

```
INPUT : standardized score series + residual PnL series (from the Stage 3 dossier)
        for every alpha in the pool
OUTPUT: composite_score(t) = Σ wᵢ · score_i(t)   — one continuous series,
        fed directly into Stage 5 (position construction)
```

Design point worth stressing: weights apply to **standardized scores** (every
alpha already expressed in standard-deviation units by the harness), so `wᵢ`
means purely **risk-budget allocation**, undistorted by each alpha's native scale.

## The method ladder, ordered by complexity

### Level 0 — Equal weight (1/k)

No joke: this is the **benchmark that must be beaten**. Empirical research
(DeMiguel et al., "Optimal Versus Naive Diversification") shows 1/k is extremely
hard to beat out-of-sample, because every fancier method pays for its complexity
in estimation error. If your method cannot beat equal weight on walk-forward —
use equal weight and stop.

### Level 1 — Inverse volatility weighting

`wᵢ ∝ 1/σᵢ` — jitterier alphas get less capital. Requires only volatility
estimates (far more stable than expected-return estimates), hence robust. The
sensible default for a time-series pool of a few dozen alphas.

### Level 2 — Risk parity

Extends inverse volatility: equalize each alpha's **risk contribution to total
portfolio risk**, accounting for the correlation matrix. Still needs no expected-
return forecast — only volatilities and correlations, both estimable reliably.
The modern mainstream choice for small-to-medium pools.

### Level 3 — Mean-variance optimization

The classic. Adds an **expected return** estimate — the weakest link. Rules if
you use it:

- Run on **residual PnL** (the Stage 3 dossier), never raw PnL — otherwise
  duplicated exposure gets funded twice;
- **Shrinkage**: pull expected returns toward a central tendency (Bayesian
  shrinkage, or simply blend with the equal-weight assumption);
- **Turnover penalty**: add `λ·|Δw|` to the objective — without it the optimizer
  jumps weights at every refit and eats costs without mercy;
- Refit **monthly/quarterly**, never daily — weights are long-horizon structure,
  not signals;
- Constraints: `wᵢ ≥ 0` (the pool is pre-filtered; no shorting alphas), sum to 1,
  per-alpha cap (e.g., 25%) so no single child dominates.

### Level 4 — Machine learning stacking (gradient boosting et al.)

A model learns the direct mapping `[k scores] → forecast`. Standard on the
cross-sectional equity side with thousands of factors and enormous samples.
For this context — time-series intraday on **one** instrument — the effective
sample is small and nonlinear models quickly learn noise instead of structure.
Practical rule of thumb: gradient boosting only earns its keep when
(a) the pool has hundreds of diverse factors, (b) years of data exist,
(c) validation is strict walk-forward at every fold. Missing any of the three →
Levels 1–2 win in practice.

## Worked example — continuing our running world

Pool of three alphas surviving Stage 3 (daily PnL volatility in % of capital):

| Alpha | Daily vol | Corr with A1 | Corr with A2 |
|---|---|---|---|
| A1 — morning momentum | 0.20% | 1.00 | −0.10 |
| A2 — opening-range mean-reversion | 0.15% | −0.10 | 1.00 |
| C — book imbalance continuation | 0.18% | 0.22 | −0.05 |

Three allocation schemes, walk-forward results (illustrative):

| Method | Weights (A1/A2/C) | Composite Sharpe |
|---|---|---|
| Equal weight | 33/33/33 | 1.55 |
| Inverse volatility | 29/39/32 | 1.68 |
| Mean-variance (with shrinkage + penalty) | 35/38/27 | 1.74 |
| Naive mean-variance (no shrinkage) | 58/12/30 | 1.31 ← loses to equal weight |

The lesson packed into the table: **method complexity only pays when it controls
estimation error** — the naive optimizer produced the worst result despite being
the most "precise", because it placed 58% of capital where the error was largest.

## Traps characteristic of this layer

1. **Weight overfitting** — trap number one, as shown above. Defense: shrinkage
   + walk-forward applied to the choice of method itself;
2. **Forgetting the equal-weight benchmark** — without a reigning champion you
   never know whether you are actually good;
3. **Weight jumps → portfolio-level turnover**: the composite changes not only
   because signals changed but because weights changed — the two turnover sources
   must be separated, and the second penalized relentlessly;
4. **Regime drift**: inter-alpha correlations are not static — refit periodically
   + monitor rolling correlations; large deviations from history are warnings;
5. **Confusing composite score with position**: the Stage 4 output is still a
   *forecast*, not a position — scaling it into size belongs to Stage 5. Do not mix.

## Handoff to Stage 5

Single output: the continuous `composite_score(t)` series plus its expectation
profile (target volatility of the whole pool). Stage 5 takes this series and
answers the last question of the inference world: **"how large a position does
this composite deserve right now?"** — via vol targeting and leverage caps —
before handing over to Stage 6 for execution.

Next stop was therefore Stage 5 — position construction.
