# Quickstart: Quantitative Developer

A Quantitative Developer wires research output into the live runner: loads
and validates `runtime.json`, builds the `PortfolioConfig` from the
research pool weights artifact, composes the Nautilus `TradingNode` (DNSE
data client, broker execution client, risk overlay, bridge strategy), and
installs the launchd job so the session starts automatically each VN
working day.

## Prerequisites

- Ready venv; run from the repo root.
- Research artifacts for the live handoff: `data/pool/alphas/*.json` +
  `index.json` (`AlphaPool`) and `data/pool/weights.json`
  (`WeightsArtifact`). The runner refuses to start without them — there is
  no silent seed fallback.
- To actually run a session: credentials in the environment (or
  `<repo>/.env`): `API_KEY`, `API_SECRET`, `ENTRADE_USERNAME`,
  `ENTRADE_PASSWORD`, optional `ENTRADE_INVESTOR_ID`; optional Telegram
  tokens for alerts. `build_node` itself needs these, so the script below
  stops at the config/handoff layer and explains the node composition.

Units, environments/account axes, runtime keys, expiry rule:
[conventions.md](conventions.md).

## Script

One complete run: load the runtime config, build the live portfolio config
from pool + weights, show what the node gets.

```bash
.venv/bin/python - <<'PY'
"""Quickstart: developer -- runtime config and the research -> live handoff."""
from pathlib import Path

from core.artifacts import AlphaPool, PoolEntry, WeightsArtifact
from trading.config_loader import load_runtime
from trading.portfolio import portfolio_config_from_pool

# 1. Load the runner config (strict: unknown keys are rejected).
config = load_runtime(Path("apps/trading/config/runtime.json"))
print("summary:", config.summary())
print("limits:", config.limits())

# 2. Research -> live handoff: WeightsArtifact weights are keyed by alpha_id;
#    the runner joins them to DSL through the pool.
pool = AlphaPool(instrument="VN30F1M")
pool.add(PoolEntry(alpha_id="alpha-1fc1ca91", dsl="ts_returns(close, 8)"))
pool.save(Path("tmp/quickstart_live"))
WeightsArtifact(
    generated="2026-09-12",
    method="inverse_vol",
    weights={"alpha-1fc1ca91": 1.0},
    window=None,
).save(Path("tmp/quickstart_live"))

artifact = WeightsArtifact.load(Path("tmp/quickstart_live"))
portfolio_config = portfolio_config_from_pool(
    artifact,
    AlphaPool.load(Path("tmp/quickstart_live")),
    config.instrument,
    limits=config.limits(),
)
print("expressions:", portfolio_config.expressions)
print("weights:", portfolio_config.weights)
PY
```

## Expected output

```
summary: VN30F1M capital=100000000VND env=live broker=entrade account=demo expiry_close=on
limits: AccountLimits(capital_vnd=100000000.0, safety_factor=0.5, margin_rate=0.05, max_contracts=10)
expressions: ('ts_returns(close, 8)',)
weights: (1.0,)
```

In production the pool and weights come from the research flow at
`data/pool/` (defaults of `AlphaPool.load()` / `WeightsArtifact.load()`); a
weights key with no matching pool `alpha_id` is a hard error — re-deliver
the pool or refit the weights.

## Node composition (dry explanation)

`trading.node.build_node(config, portfolio)` composes, but does not start,
one Nautilus `TradingNode`:

```
DNSE live bars (1-min) --> BridgeStrategy (core-gated decisions)
                               |  desired target (PortfolioOrchestrator.compute_target)
                               |  -> expiry gate -> risk decision -> orders
                               v
                       entrade demo/live execution client
                               ^
RiskOverlayActor: loss cut, staleness, exposure cap, flatten retry
```

- Environment mapping: `environment="sandbox"|"live"` in `runtime.json`
  (see [conventions.md](conventions.md#environments-and-accounts));
  `"backtest"` raises `NotImplementedError` — researchers use
  `quantcore.execution`.
- Persistence: feather stream of bars + order/position/account events to
  `data/live`; Redis-backed cache on `127.0.0.1:6379`; per-session logs
  under `data/logs/sessions/<YYYY-MM-DD>/` (`decisions.jsonl` from the
  bridge, `risk_transitions.jsonl` from the risk overlay).
- The orchestrator per bar: shape/value guards -> one batch
  `execute_batch_py` over the buffered bars -> NaN sanitization ->
  `canonical_map_py` per expression -> `composite_score_py` with the
  configured weights -> `vol_target_py` -> `to_contracts` (stateless; no
  hysteresis on the live path). Buffer warm-up (< `z_window + 320` bars)
  yields a flat `"warmup"` target.

## Running a session

```bash
.venv/bin/python apps/trading/run.py                # compose and trade the session
.venv/bin/python apps/trading/run.py --help         # flags
```

On a non-working day the runner prints one line and exits 0 before touching
the broker:

```
Not a VN market working day (source=dnse); nothing to do.
```

Session behavior:

- The session date is "now" in Asia/Ho_Chi_Minh. A non-working day (DNSE
  published calendar; falls back to the Mon-Fri heuristic with a warning if
  the calendar fetch fails) logs one line and exits 0.
- SIGTERM/SIGINT shut the node down gracefully; the position stays at the
  broker (overnight holding is intentional — there is NO end-of-day
  flatten outside the expiry rule).
- Telegram alerts (when configured) carry session start (config summary)
  and shutdown; HALT transitions are forwarded by the risk overlay.

### Automatic daily start (launchd)

1. Copy the template:
   `cp apps/trading/com.quantcore.trading.plist.example ~/Library/LaunchAgents/com.quantcore.trading.plist`
2. Replace both `<repo>` placeholders with the absolute repo path
   (`/Users/ducle/repos/quant_core`).
3. Load it: `launchctl load ~/Library/LaunchAgents/com.quantcore.trading.plist`.
4. What runs automatically: the runner starts at 08:30 local, Monday to
   Friday (Weekday 1-5 in the plist). On working days it composes the node
   and trades the session; on non-working days it exits immediately. Logs:
   `data/logs/trading-launchd.log`. Unload with
   `launchctl unload ~/Library/LaunchAgents/com.quantcore.trading.plist`.

### Flipping demo -> live

1. Edit `apps/trading/config/runtime.json`: set `"account": "live"`.
2. Launchd config alone is not enough — the runner additionally requires
   the operator flag:

```bash
.venv/bin/python apps/trading/run.py --confirm-live-account
```

Without `--confirm-live-account`, `load_runtime` rejects a live-account
config with `account=live requires --confirm-live-account`. For the launchd
path, add `<string>--confirm-live-account</string>` to the
`ProgramArguments` array of the installed plist.

## Where to go next

- Config loader / orchestrator signatures:
  [reference/core.md](reference/core.md) (contracts the runner consumes:
  `PortfolioConfig`, `TargetPosition`, `RiskDecision`) and the API surface
  above.
- Expiry-day behavior of the bridge: [conventions.md](conventions.md#expiry-rule).
- Post-session analysis: `post_mortem` and `slippage_report` in
  [reference/risk.md](reference/risk.md#post_mortem) /
  [reference/execution.md](reference/execution.md#slippage_report).
