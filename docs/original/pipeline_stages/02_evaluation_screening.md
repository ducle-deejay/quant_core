# Stage 2 — Evaluation & Screening

> Provenance: faithful English rendering of the first full presentation of
> Stage 2 (the five activities practitioners perform on the Stage 1 dossier).
> Follow-up Q&A (trial-count mechanics, threshold calibration, spec-sheet
> purpose, divergence examples, post-mortems, effective-N estimation) is not
> included here.

Every candidate passing through Stage 1 carries a dossier (daily gross/net PnL,
turnover, cost drag, score series). Stage 2 is where that dossier gets graded.
Practitioners do five things here, in processing order:

## Task 1 — Compute the full metric suite on the Stage 1 artifacts

Two layers, both must pass (this is what distinguishes evaluation from mining,
where only the forecast layer existed):

| Layer | Metrics | Question answered |
|---|---|---|
| Forecast | Rank IC at the horizon ladder {1, 5, 15, ...} + block t-stats, **ICIR**, decay profile | Is it information or noise? How long does it live? |
| Economics | **Net Sharpe** annualized, MDD, turnover, **cost drag = % of gross eaten by fees** | What survives after costs? Is it worth trading at all? |

A detail practitioners always inspect and amateurs skip: the **distribution of
daily PnL** — skew, worst days, and long/short symmetry (an alpha earning from
one side only is a sign it is betting on one regime rather than holding an edge).

## Task 2 — Temporal stability check (walk-forward)

Never grade on the full sample. History is sliced into rolling blocks (for
intraday VN30F1M: weekly/monthly blocks), and the questions are:

- IC/Sharpe per block: positive in what percentage of blocks? How bad is the
  worst block?
- Does the alpha survive thanks to **a single lucky period**? (Test: remove the
  best block — does it still work?)
- Slice by regime: high/low volatility, morning/afternoon session, trend/chop —
  learn the alpha's *habitat* and record it in the spec sheet, even when it passes.

This is exactly where the earlier flaw — "in-sample pass is enough" — gets fixed.

## Task 3 — Parameter plateau

Sweep the **alpha's** parameters (never the harness) on a grid around the chosen
point, e.g. ±30%: the alpha must show a **plateau** — neighbors of the optimum
perform nearly as well. A sharp single-point peak means noise-fitting → reject,
no matter how pretty the number.

## Task 4 — Multiple-testing control (trial count → dynamic threshold)

Every evaluation ever performed sits in a ledger. The acceptance threshold is
**not fixed** — it rises with the number of trials already executed within the
same strategy family, following the deflated Sharpe logic (Bailey &
López de Prado): after N = 500 trials, the best of 500 garbage alphas shows a
respectable Sharpe purely by chance, so the bar must be set above that level.
Cheapest task in the pipeline, most often skipped, and the one deciding whether
the whole factory is honest with itself.

## Task 5 — Gate decision + documentation

The output is a decision table like this (illustrative numbers for intraday
futures):

```
PASS if all hold simultaneously:
  ├─ Net Sharpe (walk-forward)    > deflated threshold given trial count   [e.g., > 0.8]
  ├─ ICIR                         > 0.3
  ├─ Decay                        > 0 through the target holding period
  ├─ Cost drag                    < 40% of gross
  ├─ Turnover                     < ceiling of the strategy slot
  ├─ Plateau                      stable around the optimum
  └─ % positive blocks            > 60%
```

- **PASS** → the alpha moves to Stage 3 carrying a complete **spec sheet**:
  expected holding period, expected Sharpe, capacity estimate, regime dependence,
  and **live kill criteria** ("rolling 20-day IC < 0 for two consecutive weeks
  ⇒ switch off").
- **FAIL** → rejected, but the **reason is logged in the registry** — an asset
  against anyone (including yourself, three months later) re-mining the same
  idea under a new name and fooling themselves that it is new.

## One-sentence summary

Stage 1 turns scores into economics; Stage 2 asks three questions — *is the
information real, does it survive costs, is the result stable across time and
across the number of trials* — and only an alpha answering "yes" to all three
gets to meet the pool in Stage 3.
