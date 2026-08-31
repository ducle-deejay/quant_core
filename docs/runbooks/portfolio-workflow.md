# Runbook - Portfolio Researcher workflow

Purpose: the operating cadence for the Portfolio Researcher role (decision
note DEC-017). Two recurring jobs - a weekly weight refit and a monthly
portfolio health review - plus two on-demand jobs: orthogonalizing new
candidates before they enter the pool, and registering custom combination
methods. All entry points live in `quant_api.portfolio` and are notebook-
friendly; run them from the repo root with the project `.venv`.

The pool folder (`data/pool`, or any root passed as `root=`) is the single
source of truth for which alphas are live: the research role writes per-alpha
files (`write_pool_entry` + `write_pool_index`), and both the refit below and
the live `PortfolioConfig` consume the same folder, so parity is by
construction.

## 1. Weekly refit (Monday, after the research drop)

Refit the allocation weights over the full catalog history and persist the
handoff artifact:

```python
import quant_api.portfolio as pf
pool = pf.load_pool()                      # data/pool
result = pf.refit_weights(pool, method="inverse_vol", save=True)
# -> writes data/pool/weights.json
```

- `weights.json` (`{"generated", "method", "weights", "provenance"}`) is the
  artifact the live `PortfolioConfig` reads; refresh it every week, not every
  session (weights are static per run by design, DEC-008).
- `method="equal_weight"` is the benchmark baseline; `inverse_vol` is the
  default (capped-simplex of 1/std, mirroring the engine algorithm).
- Use `window_days=N` to refit on the trailing N calendar days only when a
  regime note (spec sheet) argues for a shorter basis; default is full
  history.
- `save=False` returns the same payload without writing - use it to eyeball
  weights before committing them.

## 2. Monthly health check (first trading day of the month)

Run the in-memory review of the composite allocation:

```python
report = pf.portfolio_health_report(pool, window_days=30)
# -> full_sample_sharpe, max_drawdown, last_window_sharpe,
#    monthly_return_30d, rolling_mean_ic, verdict
```

- The report is never auto-saved (DEC-017 artifact discipline); export it
  yourself if you want a record.
- Verdict rule: `"refit"` when the last-30-day Sharpe is negative or the
  rolling mean IC of the composite vs next-bar returns is below 0.05, else
  `"ok"`. On `"refit"`, run step 1 with the same data and record the reason
  for the review log.
- The composite is inverse-vol combined; the position/PnL pipeline is the
  same canonical mapping the live loop uses (research/live parity).

## 3. Orthogonalization of new candidates (on demand)

Before a new alpha enters the pool, check whether it adds anything beyond
the existing members (Component 3 - Orthogonalization):

```python
scores = pf.pool_scores(pool)              # one engine batch call
candidate = <new alpha's score series>     # from quant_api.research
rest = [scores[k] for k in scores]
verdict = pf.orthogonalize(candidate, rest)
# verdict["verdict"] == "INCREMENTAL" -> additive; "REDUNDANT" -> skip
```

- A `"REDUNDANT"` verdict means the candidate's residual Sharpe is <= 0: it
  carries no incremental signal and should not be added to the pool.

## 4. Registering a custom combine method

The `combine_methods` registry (`pf.combine_methods`) is the extension point
for research-side combination algorithms (DEC-017):

```python
def my_combine(scores):
    return [...]  # plain Python, research-only

pf.combine_methods.register(
    "my_combine", my_combine, source="python",
    description="vol-scaled blend", replace=False,
)
pf.combine(scores, method="my_combine")    # provenance: {"method", "source": "python"}
```

- Provenance is recorded on every artifact: `"engine"` for the two defaults
  (equal_weight, inverse_vol), `"python"` for registered research methods.
- Only `equal_weight` and `inverse_vol` have research-side weight derivation
  (`refit_weights` rejects custom methods - there is no derivation rule);
  use `combine` for custom-method research, and keep `refit_weights` on the
  defaults for the live handoff.
- Validate-then-migrate: once a Python method is validated on the health
  cadence, migrate it into the Rust `CombineMethod` trait
  (`src/alpha-core/src/strategies/combination/`) and re-register it with
  `source="engine"`; the composite always runs engine-side for parity.
