"""Live node template — mirrors docs/how_to/configure_live_trading.md."""

from nautilus_trader.common import Environment
from nautilus_trader.common import LogLevel
from nautilus_trader.config import LiveExecutionEngineConfig
from nautilus_trader.config import LiveRiskEngineConfig
from nautilus_trader.config import LoggerConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId

NAME = ...  # FILL IN
TRADER_ID = ...  # FILL IN: TraderId.from_str("NAME-TAG")
ENVIRONMENT = ...  # FILL IN: Environment.LIVE

node = (
    LiveNode.builder(NAME, TRADER_ID, ENVIRONMENT)
    .with_timeout_connection(60.0)
    .with_timeout_reconciliation(30.0)
    .with_timeout_portfolio(10.0)
    .with_timeout_disconnection_secs(10.0)
    .with_delay_post_stop_secs(10.0)
    .with_delay_shutdown_secs(5.0)
    .with_reconciliation(reconciliation=True)
    .with_reconciliation_lookback_mins(None)
    .with_risk_engine_config(LiveRiskEngineConfig())
    .with_exec_engine_config(
        LiveExecutionEngineConfig(
            inflight_check_interval_ms=2_000,
            inflight_check_threshold_ms=5_000,
            inflight_check_retries=5,
            reconciliation_startup_delay_secs=10.0,
            open_check_interval_secs=None,
            open_check_open_only=True,
            open_check_lookback_mins=60,
            open_check_threshold_ms=5_000,
            position_check_interval_secs=None,
            position_check_lookback_mins=60,
            position_check_threshold_ms=5_000,
            filter_unclaimed_external_orders=False,
            filter_position_reports=False,
            allow_overfills=False,
            generate_missing_orders=True,
            snapshot_orders=False,
            snapshot_positions=False,
            purge_closed_orders_interval_mins=None,
        ),
    )
    .with_logging(LoggerConfig(stdout_level=LogLevel.INFO))
    # Cache backing (Redis or Postgres). Required for snapshots and state
    # persistence; use run(), never run_async(), when attached:
    # .with_cache_database_factory(RedisCacheConfig(host="localhost", port=6379))
    # .with_load_state(False)
    # .with_save_state(False)
    # External message bus:
    # .with_msgbus_config(...)
    # .with_external_msgbus_factory(RedisMessageBusConfig(host="localhost", port=6379))
    .add_data_client(
        ...,  # FILL IN: client name (one call per venue)
        ...,  # FILL IN: data client factory
        ...,  # FILL IN: data client config
    )
    .add_exec_client(
        ...,  # FILL IN: client name
        ...,  # FILL IN: execution client factory
        ...,  # FILL IN: execution client config
    )
    .build()
)

node.add_strategy(...)  # FILL IN
# StrategyConfig: strategy_id, order_id_tag, oms_type,
# use_uuid_client_order_ids, external_order_instrument_ids,
# manage_contingent_orders, manage_gtd_expiry

try:
    node.run()
finally:
    node.dispose()
