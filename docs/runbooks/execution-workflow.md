# Execution Researcher - operating cadence

Decision note DEC-017 governs this API. Canon: Component 6 - Trade
Scheduling, feedback edge 7->1 (slippage -> cost model).

## Weekly: slippage review (the 7->1 feedback)

1. Collect the week's session fills: `slippage_report(session_dir=...)`
   reads `<session_dir>/fills.jsonl` (fill artifacts). The bridge decision
   log alone has no fill prices - pass `fills=` explicitly or use an
   artifact that includes fills.jsonl (decision note REC-010).
2. The report decomposes implementation shortfall by session hour (Hanoi
   local), fill-size bucket and vol regime, and reports the excess versus
   the milestone-1 cost model (2.294 bp per side, DEC-006).
3. With `save=True` the summary lands in
   data/research/slippage_<week>.json - the handoff artifact consumed by
   cost-model recalibration (updating `HarnessParams.cost_per_side`) and
   sizing buffers. Updating the cost model is a deliberate action, never
   automatic.

## Researching a new execution algorithm

1. Urgency first: `urgency_analysis(gap, half_spread_bps, impact_bps,
   alpha_decay_per_bar, value_of_1bp)` -> "act-now" or "slice" (canon
   section 3.1).
2. Register the algorithm: `execution_algorithms.register(name, fn)` with
   contract `fn(gap_contracts, config) -> list[int]` (signed child-order
   quantities). Defaults: "marketable_limit" (engine-backed, live bridge
   semantics: one working order, min gap, cooldown) and "twap" (python).
3. Backtest it offline: `backtest_execution(targets, algo=name)` runs the
   Nautilus BacktestEngine over the research catalog bars with the
   target-following strategy; the report carries fills and slippage
   statistics (per-fill slippage = (fill - decision mid) * side in bp).
4. Validate (cost parity vs model), then migrate: wire the validated
   behavior into the live bridge configuration (LO/MAK, cooldown, gap).

## Notes

- The offline engine mirrors the live bridge semantics (at most one working
  order, no stacking, session discipline) - a bug here is a bug live.
- Nautilus native machinery is reused: BacktestEngine, catalog bars,
  contract builders from trading.instruments; PortfolioAnalyzer is used
  best-effort for account stats.
