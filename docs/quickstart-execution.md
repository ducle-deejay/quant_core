# Execution Researcher quickstart

Replay a target series through the real target-position strategy on the Nautilus backtest engine and review costs.

| Method | Module | Role |
| --- | --- | --- |
| `backtest_execution(targets, bars, config=None, algo="marketable_limit", catalog=None, strategy_factory=None)` | `quantcore.execution` | Bar-mode backtest running `strategy.TargetPositionStrategy` on precomputed targets. |
| `ExecutionConfig(harness, order_style, cooldown_secs, min_gap_contracts, ..., limits)` | `quantcore.execution` | Frozen configuration for the execution backtest. |
| `ExecutionReport.n_orders/.n_fills/.slippage_bps_mean/.fills/.stats/.provenance` | `quantcore.execution` | Backtest report fields (counts, fills frame, sim-account stats). |
| `plan_orders(gap_contracts, config, algo="twap")` | `quantcore.execution` | Plan and validate signed child quantities for one gap. |
| `execution_algorithms.register(name, fn, ...)` | `quantcore.execution` | Register an algorithm `fn(gap_contracts, config) -> list[int]`. |
| `urgency_analysis(inputs)` | `quantcore.execution` | Cost-of-waiting vs cost-of-acting verdict for one gap. |
| `UrgencyInputs(gap_contracts, half_spread_bps, impact_bps, alpha_decay_per_bar, value_of_1bp, hold_bars=1.0)` | `quantcore.execution` | Urgency-math inputs (non-negative, bp-based). |
| `slippage_report(fills=None, session_dir=None)` | `quantcore.execution` | Implementation-shortfall review by hour, size, and regime. |
| `SlippageReport.save(root=None)` | `quantcore.execution` | Persist the weekly slippage summary artifact. |
| `TargetSeries.from_arrays(ts, target_contracts, window, instrument)` | `core.artifacts` | Build the target series artifact the backtest consumes. |
