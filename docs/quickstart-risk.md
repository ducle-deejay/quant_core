# Risk Researcher quickstart

Own the sizing stack, apply the risk-limits policy as an opt-in backtest pass, and monitor live divergence.

| Method | Module | Role |
| --- | --- | --- |
| `backtest_portfolio(composite, bars, config=None, *, apply_policy=False)` | `quantcore.risk` | Position-level backtest; sizing always, `risk_limits` policy opt-in. |
| `RiskBacktestConfig(harness, vol_target, vol_floor, risk, limits)` | `quantcore.risk` | Frozen configuration for the portfolio backtest. |
| `RiskBacktestResult.targets/.performance/.before_performance/.policy/.interventions/.provenance` | `quantcore.risk` | Backtest report fields (targets artifact for execution). |
| `PolicyInput(ts, position, session_pnl, target, config, ledger, price)` | `quantcore.risk` | Full custom-policy decision request contract. |
| `divergence_gauges(spec, live)` | `quantcore.risk` | Divergence gauges of live behavior vs the spec sheet. |
| `post_mortem(session_dir)` | `quantcore.risk` | Session dissection of decision and transition logs. |
| `sizing_methods.register(name, fn, ...)` | `quantcore.risk` | Register a sizing method `fn(z_scores, vol_est, target_vol, drawdowns=None, floor=None)`. |
| `risk_policies.register(name, fn, ...)` | `quantcore.risk` | Register a policy `fn(PolicyInput) -> {"status", "allowed_position", "reason"}`. |
| `RiskConfig(limits, instrument, intraday_loss_limit, staleness_secs, ...)` | `core.contracts` | Live-equivalent risk configuration feeding the offline tracker. |
| `SlippageReport` (from `slippage_report(...)`) | `quantcore.execution` | Fill-cost feedback consumed by risk reviews. |
