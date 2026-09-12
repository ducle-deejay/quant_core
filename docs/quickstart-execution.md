# Quickstart: Execution Researcher

An Execution Researcher replays a target series through the Nautilus
backtest engine to measure fills and slippage (bar mode on real recorded
bars; tick mode against real trade ticks and order-book depth), plans child
orders for a position gap, and runs the trade-scheduling urgency math. The
slippage review feeds cost-model recalibration (feedback execution ->
alpha).

## Prerequisites

- Ready venv, real catalog — see
  [quickstart-alpha.md](quickstart-alpha.md#prerequisites) and
  [conventions.md](conventions.md#data-access). Tick mode needs the real
  catalog (ticks + depth10); the bars fixture can substitute for bar-mode
  bars.
- This page is self-contained: the target series is a scenario (+2
  contracts, then flat) over real catalog bars. To replay the risk step's
  actual output instead, pass `result.targets` from
  [quickstart-risk.md](quickstart-risk.md) (bounded to the same window).

Units, artifact flow: [conventions.md](conventions.md).

## Script

One complete run: bar-mode backtest, tick-mode backtest, urgency analysis.

```bash
.venv/bin/python - <<'PY'
"""Quickstart: execution research on real bars and real ticks."""
import numpy as np
import pandas as pd
from core.contracts import Instrument
from core.data import CatalogClient, DataConfig
from core.artifacts import TargetSeries
from quantcore.execution import (
    ExecutionConfig,
    UrgencyInputs,
    backtest_execution,
    urgency_analysis,
)

client = CatalogClient()

# --- Bar mode: targets over a real bar window (2026-06-01 .. 2026-09-11,
# the committed fixture window). Scenario: +2 contracts for the first half,
# flat afterwards.
bars = client.bars(DataConfig(start="2026-06-01", end="2026-09-12"))
vn30f1m = Instrument.load("VN30F1M")
half = len(bars.ts) // 2
targets = TargetSeries.from_arrays(
    bars.ts,
    np.where(np.arange(len(bars.ts)) < half, 2, 0),
    bars.window,
    vn30f1m,
)
report = backtest_execution(targets, bars)
print("bar mode:", report.provenance["data_mode"],
      "| targets:", report.n_target_changes,
      "orders:", report.n_orders,
      "fills:", report.n_fills,
      "rejected:", report.n_rejected)
print(report.fills.head(2).to_string(index=False))

# --- Tick mode: real trade ticks + order-book depth10 from the catalog.
# The catalog stores ticks/depth under the raw continuous-contract id
# 41I1G9000.HNX (same multiplier and tick size as VN30F1M).
raw = Instrument(symbol="41I1G9000", venue="HNX", multiplier=100_000.0, tick_size=0.1)
start = "2026-08-21T03:00"
small = client.bars(DataConfig(start=start, end="2026-08-21T03:10"))
t0 = pd.Timestamp(start, tz="UTC") + pd.Timedelta(minutes=1)
tick_targets = TargetSeries.from_arrays(
    pd.DatetimeIndex([t0, t0 + pd.Timedelta(minutes=2)]),
    np.array([1, 0]),
    small.window,
    raw,
)
tick_report = backtest_execution(tick_targets, small, catalog=client)
print("tick mode:", tick_report.provenance["data_mode"],
      "| orders:", tick_report.n_orders, "fills:", tick_report.n_fills)
print("stats:", tick_report.stats)

# --- Urgency math for one gap.
urgency = urgency_analysis(UrgencyInputs(
    gap_contracts=5,
    half_spread_bps=0.33,
    impact_bps=0.5,
    alpha_decay_per_bar=0.1,
    value_of_1bp=1900.0 * 100_000 * 5 / 10_000,
    hold_bars=12,
))
print("urgency:", urgency)
PY
```

## Expected output

```
bar mode: bar | targets: 17352 orders: 2 fills: 2 rejected: 0
              ts_ns  side  price  qty  decision_mid  slippage_bps
1780279200000000000     1 2006.3    2        2006.3           0.0
1784599200000000000    -1 1890.2    2        1890.2          -0.0
tick mode: tick-l2 | orders: 2 fills: 2
stats: {'n_positions': 2, 'realized_pnl_vnd': 469999.99999998184, 'account_balance': 100000000.0, 'total_pnl': 469999.99999998184}
urgency: UrgencyReport(cost_of_waiting=570000.0, cost_of_acting=394250.00000000006, verdict='act-now')
```

Honest notes:

- `n_target_changes` counts the target timestamps in the input series
  (17,352 here — every bar carries a target), NOT the number of target
  value changes. This is parity with the previous system.
- Bar mode with the default `order_style="LO"` places a limit at the
  decision price (bar close) and fills there, so `slippage_bps` is 0.0 by
  construction — the decision mid IS the fill price. Meaningful slippage
  needs tick mode (fills against the real book) and/or
  `ExecutionConfig(order_style="MAK")`.
- Tick mode: `backtest_execution` loads real trade ticks plus 10-level
  order-book depth from the catalog for the target window and matches L2.
  If depth is missing for the window it raises (set `allow_l1=True` to run
  tick-only L1 matching explicitly). The catalog keeps ticks/depth under
  `41I1G9000.HNX` — see [conventions.md](conventions.md#data-access).
- `stats.account_balance` does not move with zero-fee sim fills; the honest
  PnL is `stats.realized_pnl_vnd` / `stats.total_pnl` (instrument
  multiplier applied by the strategy itself).
- Weekly implementation-shortfall review: `slippage_report(report.fills)`
  or `slippage_report(session_dir=...)` — see
  [reference/execution.md](reference/execution.md#slippage_report). Saving
  is the explicit `SlippageReport.save()`.

## Where to go next

- Function reference: [reference/execution.md](reference/execution.md).
- Child-order planning: `plan_orders` and the `execution_algorithms`
  registry ([conventions.md](conventions.md#extension-registries)).
- The live bridge that follows targets in production:
  [quickstart-developer.md](quickstart-developer.md).
