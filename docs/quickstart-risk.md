# Quickstart: Risk Researcher

A Risk Researcher owns the sizing model (vol-target stack + drawdown
overlay) and the risk-overlay policies, and measures them with a
position-level portfolio backtest: the composite from the portfolio step is
sized into a contract series ("before"), the policy pass filters it
("after"), and both sides are reported with risk-process metrics so sizing
models are never judged on performance alone. The "after" series is the
`TargetSeries` artifact handed to execution.

## Prerequisites

- Ready venv, real catalog — see
  [quickstart-alpha.md](quickstart-alpha.md#prerequisites) and
  [conventions.md](conventions.md#data-access).
- Run [quickstart-alpha.md](quickstart-alpha.md) first (pool at
  `tmp/quickstart_pool`).

Units, artifact flow, registries: [conventions.md](conventions.md).

## Script

One complete run: composite -> `backtest_portfolio` -> inspect the target
series and both sides.

```bash
.venv/bin/python - <<'PY'
"""Quickstart: risk research -- position-level portfolio backtest."""
from pathlib import Path

from core.data import CatalogClient
from core.artifacts import AlphaPool
from quantcore.portfolio import combine, score_pool
from quantcore.risk import backtest_portfolio

pool = AlphaPool.load(Path("tmp/quickstart_pool"))
bars = CatalogClient().bars()
composite = combine(score_pool(pool, bars), method="inverse_vol", window=bars.window)

# Position-level backtest: sizing ("before") vs policy-applied ("after").
result = backtest_portfolio(composite, bars)
print("targets:", result.targets.window.n_bars, "bars,",
      "range", result.targets.target_contracts.min(), "..", result.targets.target_contracts.max())
frame = result.targets.to_frame()
print(frame[frame.target_contracts != 0].head(3).to_string(index=False))

print("before:", {k: round(v, 4) for k, v in result.before.performance.items()})
print("after: ", {k: round(v, 4) for k, v in result.after.performance.items()})
print("metrics_diff:", {k: round(v, 4) for k, v in result.metrics_diff.items()})
print("risk_process:", {k: (round(v, 2) if isinstance(v, float) else v)
                        for k, v in result.after.risk_process.items()})
print("interventions:", len(result.interventions))
print("provenance:", result.provenance)
PY
```

## Expected output

```
targets: 489446 bars, range -10 .. 10
                       ts  target_contracts
2018-08-13 02:01:00+00:00                10
2018-08-13 02:02:00+00:00                10
2018-08-13 02:03:00+00:00                10
before: {'net_sharpe': 0.1198, 'max_drawdown': -1.0107, 'total_net_pnl': 0.2422}
after:  {'net_sharpe': 0.3362, 'max_drawdown': -0.6319, 'total_net_pnl': 0.6339}
metrics_diff: {'net_sharpe': 0.2165, 'max_drawdown': 0.3788}
risk_process: {'n_interventions': 34, 'intervention_cost_estimate_vnd': 21278686.87, 'mean_abs_tracking_error': 0.01, 'max_abs_position': 10, 'trigger_counts': {'intraday-loss-limit': 2068}}
interventions: 34
provenance: {'sizing': 'vol_target_drawdown', 'sizing_source': 'engine', 'policy': 'trigger_matrix', 'policy_source': 'python', 'engine_version': '0.1.0'}
```

Honest notes:

- The trigger matrix is active on this window: the intraday loss limit
  (2% of capital) fires 2,068 times at bar level, producing 34 status
  transitions (HALT -> recover cycles recorded in `interventions`). The
  overlay flattens on each loss halt, so "after" differs from "before" —
  here it also performs better, because flattening a losing book stops the
  bleeding; treat that diff as policy behavior, not as alpha. The overfit
  guard stands: read `risk_process` next to `performance`, never the
  performance line alone.
- `intervention_cost_estimate_vnd` is the cost of trading the "after"
  series itself (fill deltas priced at the per-side cost model x price x
  multiplier); `mean_abs_tracking_error` is the mean |after - before| in
  contracts. `trigger_counts` counts EVERY policy reason (status changes
  AND gate denials), so it is larger than `n_interventions`, which counts
  only status transitions.
- Sizing and policy are resolved through the `sizing_methods` /
  `risk_policies` registries (defaults `vol_target_drawdown` /
  `trigger_matrix`). `RiskBacktestConfig` carries no method names: register
  a replacement under the same name (`replace=True`) to change the
  backtest. See [conventions.md](conventions.md#extension-registries).
- `result.targets` is a full `TargetSeries` — the artifact execution
  consumes; see [quickstart-execution.md](quickstart-execution.md).
- Divergence gauges against a spec sheet: `divergence_gauges` in
  [reference/risk.md](reference/risk.md#divergence_gauges). Session
  post-mortem over live logs: `post_mortem`.

## Where to go next

- Function reference: [reference/risk.md](reference/risk.md).
- Continue the pipeline:
  [quickstart-execution.md](quickstart-execution.md).
- The live-side counterpart of this loop (same trigger matrix, acting on
  `TargetPosition`s): [quickstart-developer.md](quickstart-developer.md).
