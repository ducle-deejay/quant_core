# Quantitative Developer quickstart

Wire research output into the live runner: core contracts, the strategy package, the safety monitor, runtime configuration, and the CLI.

| Method | Module | Role |
| --- | --- | --- |
| `Instrument.load(symbol)` | `core.instruments` | Load static reference data (multiplier, tick size). |
| `BarFrame.from_dataframe(df, *, instrument_id="", bar_type="")` | `core.data` | Wrap a real bar frame for research and live consumers. |
| `CatalogClient(root=None)` | `core.data` | Read recorded ticks/depth from the data catalog. |
| `to_contracts(z, price, cap, instrument, limits)` | `core.mapping` | Single score-to-contracts conversion (shared research/live). |
| `max_contracts_at(price, instrument, limits)` | `core.mapping` | Max leverage headroom at a price. |
| `hysteresis_band_contracts(band, cap, price, instrument, limits)` | `core.mapping` | No-trade dead-zone width in contracts. |
| `apply_hysteresis(raw, prev, band_contracts)` | `core.mapping` | Hold-previous rule for contract moves. |
| `close_returns(close)` / `rolling_vol(close, window, bars_per_day)` / `sanitize_scores(series)` | `core.signal` | Return, volatility, and NaN-sanitization primitives. |
| `apply_expiry_gate(ts_utc, target_contracts, current_contracts, state, *, enabled, close_time_local="14:00", tz="Asia/Ho_Chi_Minh", working_dates=())` | `core.expiry` | VN30F1M expiry-day force-flat / reduce-only gate. |
| `vn30_front_month_expiry_date_local(ts_utc, working_dates=())` | `core.expiry` | Front-month expiry date for a timestamp. |
| `vn30_front_month_expiry_cutoff_utc(ts_utc, working_dates=())` | `core.expiry` | Expiry-day cutoff as a UTC timestamp. |
| `TargetPosition(ts, target_contracts, z_target, reason, components)` | `core.contracts` | Portfolio's desired signed position (the decision unit). |
| `AccountLimits(capital_vnd, safety_factor, margin_rate, max_contracts)` | `core.contracts` | Account sizing limits (max_contracts lives here). |
| `Registry.get/call/register` | `core.registry` | Sizing/policy/algorithm extension registries. |
| `PortfolioOrchestrator(config, instrument).compute_target(bars, ts)` | `strategy.portfolio` | Bars in, one `TargetPosition` out (pure alpha_core pipeline). |
| `portfolio_config_from_pool(artifact, pool=None, instrument=None, *, limits=None)` | `strategy.portfolio` | Live portfolio config from the weights artifact. |
| `TargetPositionStrategy(config, portfolio)` | `strategy.target_position` | The one decision-per-bar strategy; denials arrive as `OrderDenied`. |
| `SafetyMonitor(instrument_id, bar_type, safety, limits, risk_engine, monitor_strategy_id, bridge_strategy_id, transition_log_path=None, notifier=None)` | `trading.safety` | Drives `RiskEngine.set_trading_state`; flattens on HALTED. |
| `evaluate_safety(*, session_open, now, last_bar_ts, staleness_secs, position, max_contracts, session_pnl_vnd, capital_vnd, intraday_loss_limit)` | `trading.safety` | Pure safety evaluator: loss > stale > exposure > ACTIVE. |
| `SessionPnlBook(multiplier).record_fill / .mark / .on_bar` | `trading.safety` | Intraday PnL book; positions carry, PnL resets daily. |
| `SafetyConfig(intraday_loss_limit=0.02, staleness_secs=60.0)` | `trading.safety` | The two safety knobs (config-driven, no others). |
| `load_runtime(path, *, confirm_live_account=False)` | `trading.config_loader` | Load and validate `runtime.json` (unknown keys rejected). |
| `build_node(config, portfolio, *, loop=None)` | `trading.node` | Compose the live TradingNode (DNSE data, entrade execution, both strategies). |
| `runtime.json` key `instrument` | `apps/trading/config/runtime.json` | Symbol of the traded front month (e.g. `VN30F1M`). |
| `runtime.json` key `capital_vnd` | `apps/trading/config/runtime.json` | Account capital in VND feeding sizing limits. |
| `runtime.json` key `environment` | `apps/trading/config/runtime.json` | `backtest` / `sandbox` / `live` (runner rejects backtest). |
| `runtime.json` key `broker` | `apps/trading/config/runtime.json` | Execution adapter key (`entrade`). |
| `runtime.json` key `account` | `apps/trading/config/runtime.json` | `demo` or `live` (live needs the CLI confirmation flag). |
| `runtime.json` key `close_positions_on_expiry_day` | `apps/trading/config/runtime.json` | Master switch for the expiry gate. |
| `runtime.json` key `safety.intraday_loss_limit` | `apps/trading/config/runtime.json` | Session loss fraction of capital that halts trading (0.02). |
| `runtime.json` key `safety.staleness_secs` | `apps/trading/config/runtime.json` | Bar-silence seconds (open session) that halt trading (60). |
| `run.py --config PATH` | `apps/trading/run.py` | Run the live session with a non-default config path. |
| `run.py --confirm-live-account` | `apps/trading/run.py` | Required confirmation when the config selects `account=live`. |
