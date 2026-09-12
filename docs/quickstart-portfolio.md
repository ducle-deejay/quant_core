# Quickstart: Portfolio Researcher

A Portfolio Researcher takes the delivered alpha pool, scores every alpha
over a bar window, combines the scores into one composite in z-units, runs
the weight-refit cadence that produces the live handoff artifact, and reads
the portfolio health report that drives the monthly allocation review.

## Prerequisites

- Ready venv, real catalog (or the June-September fixture bars) — see
  [quickstart-alpha.md](quickstart-alpha.md#prerequisites) and
  [conventions.md](conventions.md#data-access).
- Run [quickstart-alpha.md](quickstart-alpha.md) first: it writes the pool
  this script loads (`tmp/quickstart_pool`).

Units, artifact flow, and the registry notes:
[conventions.md](conventions.md).

## Script

One complete run: load the pool, score, combine, refit weights, health
report.

```bash
.venv/bin/python - <<'PY'
"""Quickstart: portfolio research on the delivered pool."""
from pathlib import Path

from core.data import CatalogClient
from core.artifacts import AlphaPool, WeightsArtifact
from quantcore.portfolio import combine, health_report, refit_weights, score_pool

pool = AlphaPool.load(Path("tmp/quickstart_pool"))  # written by quickstart-alpha
bars = CatalogClient().bars()
print("pool:", len(pool.entries), "alphas | bars:", bars.window.n_bars)

# 1. Score every pool alpha over the bars (RAW engine rows: warmup NaN included).
scores = score_pool(pool, bars)

# 2. Combine into one composite (z-units); combine standardizes internally.
composite = combine(scores, method="inverse_vol", window=bars.window)
print("method:", composite.method)
print("weights:", {a: round(w, 4) for a, w in zip(composite.alpha_ids, composite.weights)})

# 3. Refit cadence: same weights as a saveable handoff artifact.
artifact = refit_weights(pool, bars)
print("saved:", artifact.save(Path("tmp/quickstart_pool")))

# 4. Monthly allocation-review input.
health = health_report(composite, bars)
print("full_sample_sharpe=%.3f max_drawdown=%.3f" % (health.full_sample_sharpe, health.max_drawdown))
print("last_window_sharpe=%.3f rolling_mean_ic=%.5f verdict=%s" % (
    health.last_window_sharpe, health.rolling_mean_ic, health.verdict))
PY
```

## Expected output

```
pool: 6 alphas | bars: 489446
method: inverse_vol
weights: {'alpha-12f7688d': 1.0, 'alpha-1fc1ca91': 0.0, 'alpha-3aac71d8': 0.0, 'alpha-4852dff1': 0.0, 'alpha-d4a70e7e': 0.0, 'alpha-da1d20a2': 0.0}
saved: tmp/quickstart_pool/weights.json
full_sample_sharpe=-4.803 max_drawdown=-8.229
last_window_sharpe=-4.836 rolling_mean_ic=0.02698 verdict=refit
```

Honest notes:

- `score_pool` returns the RAW engine rows — the first `window - 1` bars of
  every rolling operator are NaN by engine contract. Do not forward-fill
  them: `combine` standardizes internally, and sanitizing here would change
  the volatility estimates and therefore the weights.
- Parity-locked combination semantics (they look sharp-edged, by design —
  these are the pre-redesign system's exact semantics): the volatility
  estimate of an alpha is poisoned by ANY non-finite entry, so an alpha
  whose raw row still carries warmup NaN gets weight 0, and a standardized
  row with any NaN maps entirely to zeros. Here only `alpha-12f7688d`
  (`close - ewma(close, 8)`, EWMA needs no warmup window) has a NaN-free
  row, so it is the single survivor and takes the full budget (1.0); the
  other five get 0.0 and contribute nothing to the composite. A pool whose
  alphas all carry warmup NaN would fall back to equal weights.
- Weights are fractions summing to 1, capped-simplex projected (min 0.01,
  max 0.5; the caps bind only when two or more alphas are eligible).
- `verdict="refit"` means the last 30 calendar days were weak
  (`last_window_sharpe < 0` or `rolling_mean_ic < 0.05`); the health report
  is the monthly review input, in memory only.
- `WeightsArtifact` weights are keyed by `alpha_id`. The live runner joins
  them back to DSL through `AlphaPool.load()` — see
  [quickstart-developer.md](quickstart-developer.md). Zero-weight alphas
  still enter the live expression list (weighted 0), so curate the pool
  before refitting.

## Where to go next

- Function reference: [reference/portfolio.md](reference/portfolio.md).
- Candidate admission against the pool: `orthogonalize` in
  [reference/portfolio.md](reference/portfolio.md#orthogonalize).
- Custom combination methods: the `combine_methods` registry in
  [conventions.md](conventions.md#extension-registries).
- Continue the pipeline: [quickstart-risk.md](quickstart-risk.md).
