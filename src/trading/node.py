"""Nautilus TradingNode composition for the live runner (single runner path)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from nautilus_trader.common import Environment
from nautilus_trader.common.config import LoggingConfig
from nautilus_trader.config import CacheConfig
from nautilus_trader.config import DatabaseConfig
from nautilus_trader.config import RoutingConfig
from nautilus_trader.config import StreamingConfig
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.config import LiveDataEngineConfig
from nautilus_trader.live.config import LiveExecEngineConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.data import Bar
from nautilus_trader.model.events import AccountState
from nautilus_trader.model.events import OrderAccepted
from nautilus_trader.model.events import OrderCanceled
from nautilus_trader.model.events import OrderExpired
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.events import OrderRejected
from nautilus_trader.model.events import OrderSubmitted
from nautilus_trader.model.events import PositionChanged
from nautilus_trader.model.events import PositionClosed
from nautilus_trader.model.events import PositionOpened

from core import Account
from core import AccountLimits
from core import Instrument
from core import PortfolioConfig
from core import RiskConfig
from market_data.instrument_provider import instrument_definition_path
from market_data.instruments import load_futures_instrument_spec
from market_data.notify import trading_notifier_from_env
from trading.adapters.dnse.config import DNSE_DATA_CLIENT_NAME
from trading.adapters.dnse.config import DnseDataClientConfig
from trading.adapters.dnse.data import build_bar_type_for_symbol
from trading.adapters.dnse.factory import DnseLiveDataClientFactory
from trading.adapters.entrade.config import DNSE_EXECUTION_CLIENT_NAME
from trading.adapters.entrade.factory import EntradeLiveExecClientFactory
from trading.config_loader import RuntimeConfig
from trading.credentials import load_credentials
from trading.credentials import optional_env
from trading.credentials import require_env
from trading.portfolio import PortfolioOrchestrator
from trading.risk.overlay import RiskOverlayActor
from trading.strategies.bridge import BridgeConfig
from trading.strategies.bridge import BridgeStrategy
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
TRADER_ID = "TRADER-001"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
#: Nautilus bar resolution for the live feed (1-minute bars).
BAR_RESOLUTION = "1"
#: Bridge id formula (v1): f"{component_id}-{order_id_tag}" ->
#: "BridgeStrategy-bridge"; the risk overlay subscribes to the bridge's
#: order topic under this exact id.
BRIDGE_STRATEGY_ID = "BridgeStrategy-bridge"

#: Arrow-serializable stream subset, verified against the installed
#: nautilus_trader 1.231.0 wheel (persistence/writer.py ``include_types``
#: filter + serialization.arrow registry): every type below has a registered
#: Arrow schema in the wheel (54 registered), so the feather stream writes
#: bars, order events, position events, and account state without loss.
STREAMABLE_TYPES = [
    Bar,
    OrderSubmitted,
    OrderAccepted,
    OrderRejected,
    OrderCanceled,
    OrderExpired,
    OrderFilled,
    PositionOpened,
    PositionChanged,
    PositionClosed,
    AccountState,
]

#: Redis backing for the cache database (orders/positions/state persistence).
CACHE_DATABASE = DatabaseConfig(type="redis", host="127.0.0.1", port=6379)

#: RuntimeConfig.environment -> nautilus_trader Environment. This runner only
#: composes live runtimes; "backtest" raises NotImplementedError (researchers
#: use quantcore.execution).
ENVIRONMENTS: dict[str, Environment] = {
    "sandbox": Environment.SANDBOX,
    "live": Environment.LIVE,
}


def session_artifacts_dir(session_date: str) -> Path:
    """Per-session artifact directory under ``data/logs/sessions``."""
    return ROOT / "data" / "logs" / "sessions" / session_date


def session_date_iso(now: datetime | None = None) -> str:
    """The Asia/Ho_Chi_Minh calendar date of ``now`` (default: wall clock)."""
    if now is None:
        now = datetime.now(tz=VN_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=VN_TZ)
    else:
        now = now.astimezone(VN_TZ)
    return now.date().isoformat()


def _nautilus_environment(environment: str) -> Environment:
    """Map ``RuntimeConfig.environment`` to the Nautilus runtime environment.

    Raises
    ------
    NotImplementedError
        For ``"backtest"``: the live runner never composes a backtest;
        researchers use ``quantcore.execution``.
    ValueError
        For any other unknown environment string.
    """
    if environment == "backtest":
        raise NotImplementedError(
            "environment 'backtest' is not supported by the live runner; "
            "researchers use quantcore.execution"
        )
    try:
        return ENVIRONMENTS[environment]
    except KeyError:
        raise ValueError(
            f"environment must be one of {sorted(ENVIRONMENTS)}, got {environment!r}"
        ) from None


def _entrade_execution_factory(config: RuntimeConfig) -> Any:
    """Build the entrade execution client config for the configured account.

    Credentials are resolved from the process environment (``ENTRADE_*``),
    exactly as the paper runner did; ``ENTRADE_INVESTOR_ID`` is optional and
    auto-resolved from the auth token when unset. The broker account boundary
    (demo/live) maps from ``config.account``.
    """
    from trading.adapters.entrade.config import EntradeExecClientConfig
    from trading.adapters.entrade.transport import EntradeEnvironment

    environment = {
        Account.DEMO: EntradeEnvironment.DEMO,
        Account.LIVE: EntradeEnvironment.LIVE,
    }[config.account]
    instrument_spec = load_futures_instrument_spec(
        instrument_definition_path(config.instrument.symbol)
    )
    routing = RoutingConfig(default=True, venues=frozenset({instrument_spec.venue}))
    investor_id = optional_env("ENTRADE_INVESTOR_ID")
    return EntradeExecClientConfig(
        instrument_spec=instrument_spec,
        username=require_env("ENTRADE_USERNAME"),
        password=require_env("ENTRADE_PASSWORD"),
        investor_id=int(investor_id) if investor_id is not None else None,
        environment=environment,
        routing=routing,
    )


#: Broker adapter registry keyed by ``RuntimeConfig.broker``.
_BROKERS: dict[str, Callable[[RuntimeConfig], Any]] = {
    "entrade": _entrade_execution_factory,
}


def _make_node_config(
    environment: Environment,
    data_client_config: DnseDataClientConfig,
    exec_client_config: Any,
) -> TradingNodeConfig:
    """The full live node config.

    - ``cache``: Redis-backed cache database (kernel.py constructs a
      ``CacheDatabaseAdapter`` over ``nautilus_pyo3.RedisCacheDatabase``
      automatically from ``CacheConfig(database=...)``).
    - ``streaming``: feather stream of the verified ``STREAMABLE_TYPES`` to
      ``data/live`` (kernel writes under ``<catalog_path>/LIVE/<instance_id>``).
    - ``exec_engine``: order and position state snapshots persisted to Redis
      at every state update.
    - ``load_state``/``save_state``: the kernel calls the strategy
      ``on_load``/``on_save`` hooks via ``Trader.load/save``.
    """
    return TradingNodeConfig(
        environment=environment,
        trader_id=TRADER_ID,
        logging=LoggingConfig(log_level=os.getenv("LOG_LEVEL", "INFO"), log_colors=False),
        data_engine=LiveDataEngineConfig(validate_data_sequence=True),
        exec_engine=LiveExecEngineConfig(
            reconciliation=True,
            snapshot_positions=True,  # risk overlay seeds position from cache on start
            snapshot_orders=True,  # order state snapshots -> Redis on every update
        ),
        cache=CacheConfig(database=CACHE_DATABASE),
        streaming=StreamingConfig(
            catalog_path=str(ROOT / "data" / "live"),
            include_types=STREAMABLE_TYPES,
        ),
        load_state=True,  # bridge/overlay on_load hooks run before start
        save_state=True,  # bridge/overlay on_save hooks run at stop
        strategies=[],  # both strategies are added programmatically below
        data_clients={DNSE_DATA_CLIENT_NAME: data_client_config},
        exec_clients={DNSE_EXECUTION_CLIENT_NAME: exec_client_config},
    )


def build_node(
    config: RuntimeConfig,
    portfolio: PortfolioConfig,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> TradingNode:
    """Build the live TradingNode: DNSE data + broker execution + risk + bridge.

    Parameters
    ----------
    config : RuntimeConfig
        Runtime selection (instrument, capital, environment, broker,
        account, expiry close switch) from :mod:`trading.config_loader`.
    portfolio : PortfolioConfig
        Portfolio configuration (expressions/weights from the pool weights
        artifact; limits embedded), e.g. via
        ``trading.portfolio.portfolio_config_from_pool``.
    loop : asyncio.AbstractEventLoop | None
        Optional event loop handed to the Nautilus TradingNode.

    Returns
    -------
    TradingNode
        The composed, not-yet-built node; the runner calls ``node.build()``
        then blocks in ``node.run()``.
    """
    load_credentials()
    environment = _nautilus_environment(config.environment)

    instrument_spec = load_futures_instrument_spec(
        instrument_definition_path(config.instrument.symbol)
    )
    bar_type = build_bar_type_for_symbol(
        symbol=instrument_spec.symbol,
        resolution=BAR_RESOLUTION,
        venue=instrument_spec.venue,
    )
    routing = RoutingConfig(default=True, venues=frozenset({instrument_spec.venue}))

    data_client_config = DnseDataClientConfig(
        api_key=require_env("API_KEY"),
        api_secret=require_env("API_SECRET"),
        instrument_spec=instrument_spec,
        routing=routing,
    )
    try:
        broker_factory = _BROKERS[config.broker]
    except KeyError:
        raise ValueError(
            f"broker must be one of {sorted(_BROKERS)}, got {config.broker!r}"
        ) from None
    exec_client_config = broker_factory(config)

    node_config = _make_node_config(environment, data_client_config, exec_client_config)
    node = TradingNode(config=node_config, loop=loop)
    node.add_data_client_factory(DNSE_DATA_CLIENT_NAME, DnseLiveDataClientFactory)
    node.add_exec_client_factory(DNSE_EXECUTION_CLIENT_NAME, EntradeLiveExecClientFactory)

    # Telegram alerting (failure-safe; None when TRADING_TELEGRAM_* unset).
    notifier = trading_notifier_from_env()

    # Risk overlay first so the bridge can reference the instance.
    artifacts = session_artifacts_dir(session_date_iso())
    risk_config = RiskConfig(
        limits=AccountLimits(capital_vnd=config.capital_vnd),
        instrument=config.instrument,
    )
    risk_actor = RiskOverlayActor(
        bar_type=bar_type,
        risk_config=risk_config,
        order_id_tag="risk",
        bridge_strategy_id=BRIDGE_STRATEGY_ID,
        transition_log_path=str(artifacts / "risk_transitions.jsonl"),
        notifier=notifier,
    )

    # Portfolio orchestrator (pure alpha_core decisions).
    orchestrator = PortfolioOrchestrator(config=portfolio, instrument=config.instrument)

    # Bridge strategy, constructed directly (BridgeConfig is a plain
    # dataclass; Nautilus ImportableStrategyConfig cannot round-trip it).
    bridge = BridgeStrategy(
        BridgeConfig(
            instrument_id=str(bar_type.instrument_id),
            bar_type=str(bar_type),
            portfolio=orchestrator,
            risk=risk_actor,
            notifier=notifier,
            expiry_enabled=config.close_positions_on_expiry_day,
            decision_log_path=str(artifacts / "decisions.jsonl"),
        ),
    )

    node.trader.add_strategy(risk_actor)
    node.trader.add_strategy(bridge)

    if node_config.load_state:
        # The kernel's own trader.load() ran at node construction (kernel.py),
        # when config.strategies was empty because both strategies are added
        # programmatically above; trigger the load now so the on_load hooks
        # actually run before start.
        node.trader.load()

    return node
