# Quickstart: Alpha Researcher

An Alpha Researcher hand-writes seed expressions in the DSL, evaluates them
against the real market data (canonical simulation, metrics, gate verdict),
screens batches, mines the GA from passing seeds, and delivers passing
alphas into the pool the Portfolio Researcher consumes.

## Prerequisites

- A ready venv at `.venv/` (run everything as `.venv/bin/python` from the
  repo root).
- The research catalog: `QUANTCORE_CATALOG` defaults to
  `/Users/ducle/repos/nox_system/data/catalog` (already the default in
  `core.data`), so no configuration is needed.
- For fast iteration, the committed fixture
  `tmp/fixtures/bars_20260601_20260911.parquet` replaces the catalog bars
  (identical values for that window); see [conventions.md](conventions.md#data-access).

Units and artifact flow: [conventions.md](conventions.md).

## Script

One complete run: evaluate a seed, screen the seed batch, watch the gate
refuse an OUT verdict, and persist the pool. Copy-paste-execute:

```bash
.venv/bin/python - <<'PY'
"""Quickstart: alpha research on the real catalog."""
from pathlib import Path

from core.data import CatalogClient
from core.artifacts import AlphaPool, PoolEntry
from quantcore.alpha import (
    AlphaConfig,
    build_spec_sheet,
    deliver,
    evaluate_seed,
    screen_batch,
)

SEEDS = [
    "close - ewma(close, 8)",
    "ts_returns(close, 8)",
    "-ts_returns(close, 5)",
    "ts_trend_slope(close, 20)",
    "ts_returns(close, 8) * ts_zscore(volume, 20)",
    "close / ts_max(close, 20) - 1",
]

# 1. Load the full 1-minute VN30F1M history (default catalog path).
bars = CatalogClient().bars()
print("bars:", bars.window.n_bars, bars.window.start, "->", bars.window.end)

# 2. Evaluate one seed: canonical simulation + gate verdict.
tear = evaluate_seed(SEEDS[1], bars)
print("alpha_id:", tear.alpha_id)
print("verdict:", tear.verdict, "reasons:", tear.reasons)
print("net_sharpe=%.3f best_abs_ic=%.4f cost_drag_pct=%.1f icir=%.4f" % (
    tear.metrics["net_sharpe"],
    tear.metrics["best_abs_ic"],
    tear.metrics["cost_drag_pct"],
    tear.metrics["icir"],
))

# 3. Screen the whole seed batch and show the funnel.
result = screen_batch(SEEDS, bars)
print("funnel:", result.funnel)

# 4. The gate refuses an OUT verdict: deliver() raises.
spec = build_spec_sheet(tear, bars)
try:
    deliver(AlphaPool(instrument="VN30F1M"), tear, spec)
except ValueError as error:
    print("deliver refused:", str(error)[:80], "...")

# 5. Research continuation: a non-passing seed can still be tracked by
#    adding a PoolEntry directly (flagged); passing alphas go through
#    deliver(). Persist the pool either way with pool.save().
pool = AlphaPool(instrument="VN30F1M")
for i, dsl in enumerate(SEEDS):
    sheet = result.tear_sheets[i]
    sheet_spec = build_spec_sheet(sheet, bars)
    if sheet.verdict == "IN":
        deliver(pool, sheet, sheet_spec)          # gated path
    else:
        pool.add(PoolEntry(                        # research continuation
            alpha_id=sheet.alpha_id,
            dsl=sheet.dsl,
            tear_sheet=sheet,
            spec_sheet=sheet_spec,
            tags=("seed", "research-continuation"),
        ))
print("pool entries:", len(pool.entries))
print("saved:", pool.save(Path("tmp/quickstart_pool")))
PY
```

## Expected output

```
bars: 489446 2018-08-13 02:00:00+00:00 -> 2026-09-11 07:45:00+00:00
alpha_id: alpha-1fc1ca91
verdict: OUT reasons: ('cost_drag', 'net_sharpe', 'walk_forward', 'icir')
net_sharpe=-5.439 best_abs_ic=0.0672 cost_drag_pct=507.2 icir=-0.1015
funnel: {'total_candidates': 6, 'ic_pass_count': 6, 'drag_pass_count': 0, 'survivor_count': 0}
deliver refused: cannot deliver alpha 'alpha-1fc1ca91' with verdict 'OUT'; reasons: ('cost_drag', ...
pool entries: 6
saved: tmp/quickstart_pool
```

Honest note: the 6 legacy seed expressions do NOT pass the current
`GateCriteria` on full history (all verdict OUT, all fail the cost-drag and
net-Sharpe checks). `deliver()` refuses OUT verdicts by design; the direct
`PoolEntry` path above keeps research on a non-passing seed moving (for
example while a variant is being bred) without pretending it passed the
gate. Passing alphas must go through `deliver()` — the pool handoff artifact
that the live weights join is built from `PoolEntry`s.

The alpha ids are deterministic (SHA-256 of the canonical DSL, 8 hex chars),
so `alpha-1fc1ca91` is stable across runs and machines.

## Where to go next

- Function reference: [reference/alpha.md](reference/alpha.md); data loading
  in [reference/core.md](reference/core.md#catalogclient).
- Continue the pipeline: [quickstart-portfolio.md](quickstart-portfolio.md)
  (consumes the pool saved above).
- GA mining from passing seeds: `mine_seeds` in
  [reference/alpha.md](reference/alpha.md#mine_seeds).
