# Quant Risk Researcher - operating cadence

Decision note DEC-017 governs this API. Canon: Component 5 - Position
Construction (sizing ownership), Component 7 - Risk Overlay and Monitoring.
Vocabulary: the risk role runs PORTFOLIO BACKTESTS, never "replays".

## Model research cycle (register -> backtest -> validate -> migrate)

1. Research a new sizing model or risk policy in Python:
   - `sizing_methods.register(name, fn)` - uniform signature
     `fn(z_scores, vol_est, target_vol, drawdowns=None, floor=None) -> list[float]`;
     engine defaults: vol_target, drawdown_overlay, vol_target_drawdown.
   - `risk_policies.register(name, fn)` - contract
     `fn(policy_input: dict) -> dict` returning
     {"status", "reason", "allowed_position"}; default "trigger_matrix"
     reuses the live RiskLedger (trading.risk.state).
2. Backtest the model: `backtest_portfolio(composite, sizing=..., policy=...,
   config=...)` -> report with BEFORE (sizing only) and AFTER (policy
   applied) performance metrics AND risk-process metrics (interventions,
   intervention cost, tracking error, max position, trigger counts).
   JUDGE ON RISK-PROCESS METRICS + BEHAVIOR, NOT PERFORMANCE ALONE -
   optimizing a sizing model on portfolio Sharpe overfits (DEC-017 guard).
3. Validate (out-of-sample windows, walk-forward), then MIGRATE:
   - sizing model -> port into the Rust SizingMethod trait;
   - risk policy -> live RiskLedger wiring;
   - run `build_overlay_config(save=True)` -> data/state/risk_overlay.json,
     the handoff artifact consumed by the live overlay.

## Weekly

Divergence gauges on live session data: `divergence_gauges(expected, live)`
- gauge 1 rolling Information Coefficient vs spec sheet,
- gauge 2 implementation shortfall vs cost model,
- gauge 3 position tracking error,
- gauge 4 fill/reject rates, latency, feed gaps.
Escalation: warning/critical bands trigger review; a spec-sheet kill
criterion that fires switches the alpha off (canon Component 7 section 3.4).

## After a bad session

`post_mortem(session_dir)` - reads decisions.jsonl + risk_transitions.jsonl,
returns the event timeline, loss-attribution notes and candidate
recommendations (new gates / kill criteria) as DATA; recommendations are
reviewed before they become gates (feedback 2->0).

## Monthly

Review sizing/overlay models on the past month's window with
`backtest_portfolio`; review risk budget. Quarterly: risk budget review and
harness version review (framework-lifecycle operating cadence).
