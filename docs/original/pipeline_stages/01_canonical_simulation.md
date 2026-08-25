# Stage 1 — Canonical Simulation

> Provenance: faithful English rendering of the first full presentation of
> Stage 1 (the four activities practitioners perform on alphas mined in
> Stage 0). Follow-up Q&A (operator-by-operator explanation of the mapping,
> the PnL formula dissection, window selection, etc.) is not included here.

At Stage 1 the practitioner does exactly four things — all applied to **every**
candidate coming out of Stage 0, under one uniform rule.

## 1. Apply the canonical mapping — a single formula shared by every alpha

```
score → EWMA smoothing → rolling z-score → no-trade band → cap ±L
      = canonical position p_t
```

There is no scenario where one alpha uses band 0.3 and another uses cap 1.5 by
its author's taste. **The conversion rule is a factory-wide asset**, because the
purpose of this stage is *comparability* — only with a common unit of measure
can candidates be ranked against each other.

## 2. Compute canonical PnL net-of-cost

```
pnl_t = p_(t−1) × r_t − c × |Δp_t|
```

The cost `c` is flat (fee plus a half-spread approximation), and turnover is
measured from |Δp|. The whole computation runs vectorized over the full history
in tens of milliseconds per alpha.

## 3. Emit the standardized artifact bundle for downstream stages

Every alpha leaves Stage 1 with a fixed dossier:

- Daily **gross/net PnL series** (raw material for Sharpe scoring in Stage 2,
  for pool regression in Stage 3, for weights in Stage 4)
- **Actual turnover** of the canonical position
- **Cost drag** = percentage of gross consumed by costs

This dossier is stored in an **alpha registry** together with metadata (params,
code version, creation date, trial count) — this is the firm's living library,
not a pile of loose files.

## 4. What this stage deliberately does NOT do

- No real order simulation, no entry/exit logic, no queue matching — that is the
  job of the event-driven backtest, reserved for the few dozen finalists that
  survive Stages 2–3.
- No per-alpha sizing tuning — an alpha that survives only under specially tuned
  sizing is fitting noise and will die live anyway.

## One-sentence summary

**Stage 1 translates forecast language into economic language under a single
uniform sizing convention.** From this point on, "a good alpha" is an objective
concept (net-of-cost, common leverage) rather than each researcher's subjective
impression.
