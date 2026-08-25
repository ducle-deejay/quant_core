# Pipeline Overview — The Modern 8-Stage System

> Provenance: faithful English rendering of the response in which the original
> 5-stage practitioner pipeline was redesigned into the modern 8-stage pipeline
> (first full presentation of the redesigned pipeline). Follow-up Q&A is not
> included in this file.

## Guiding principle

The redesigned pipeline separates *inference* from *trading*. Early stages live
purely in **score space** — nobody decides to buy or sell anything there. All
money decisions are pushed to the end and executed **once, centrally, in one
place**.

## The pipeline

```
Stage 0: Alpha mining           [NEW]       DSL grammar × seeds × GA/enumeration
                                            → thousands of score functions

Stage 1: Canonical simulation   [MODIFIED]  every score goes through the SAME
                                            canonical mapping rule
                                            → canonical position → net-of-cost PnL

Stage 2: Evaluation             [MODIFIED]  IC/ICIR across horizons + decay profile
                                            + Sharpe of canonical PnL + turnover
                                            + walk-forward + trial-count log

Stage 3: Orthogonalization      [MODIFIED]  regress out the PnL of the current pool
                                            → only the residual is considered
                                            for admission

Stage 4: Combination            [MODIFIED]  z-score each alpha → weighted sum
                                            (weights from risk-parity / MVO on
                                            residual PnL, or GBDT stacking)
                                            → composite score (continuous)

Stage 5: Position construction  [NEW]       composite score → target position
                                            via vol targeting + leverage cap

Stage 6: Trade scheduling       [NEW]       current position → target position,
                                            order slicing, cost-aware execution

Stage 7: Risk overlay           [NEW]       kill switch, exposure cap,
                                            live-vs-backtest divergence alert
```

## What changes at each stage versus the old pipeline

| Stage | Old | New |
|---|---|---|
| **0** | Implicit — humans hand-write each rule | Becomes a dedicated machine stage: operator grammar generates formulas, genetic algorithms breed them, human hypotheses serve as seeds |
| **1** | Each alpha simulates its own trades | **Canonicalization**: every score passes through the same score→position conversion. This is the keystone — thanks to it, alpha fitness values become **absolutely comparable**, and simulation runs vectorized |
| **2** | Trade-level metrics (entry/exit PnL) | Score-level metrics first (**IC, decay**) — measure forecast quality independently of sizing; Sharpe of canonical PnL serves only as the second verification layer |
| **3** | Correlation cutoff at 0.5–0.6 | Orthogonalization computed on PnL streams |
| **4** | MVO on signals bounded in [-1, 1] | Combining happens in standardized score space; output is a continuous composite score, no longer confined to [-1, 1] |
| **5–7** | Did not exist | All money decisions concentrated here, performed exactly once |

## Two consequences you will feel immediately

1. **Turnover becomes a controllable variable.** Instead of every alpha firing
   its own orders, only Stages 5–6 decide how much position change is warranted.
   For intraday VN30F1M where costs eat the edge basis-point by basis-point, this
   is the shift from "dying by crossfire" to having a single pilot.

2. **Alphas become manageable assets.** A score function is stateless and can be
   tested by IC in seconds across five years of data. The Chinese factories run
   thousands of formulas per day precisely because of this property — no magic,
   just this mechanical advantage.

## Where the old pipeline stood

The old skeleton was already correct for Stages 1–4; what was missing was
Stage 0 and the entire 5–7 cluster. The suggested entry point for deeper study
was Stage 1 (canonical mapping), because it is the coupling joint between the
score world being built and the PnL world used for judging.
