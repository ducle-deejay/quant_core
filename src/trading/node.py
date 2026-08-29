from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
from nautilus_trader.adapters.sandbox.factory import SandboxLiveExecClientFactory
from nautilus_trader.common.config import LoggingConfig
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.config import LiveExecClientConfig
from nautilus_trader.config import RoutingConfig
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.config import LiveDataEngineConfig
from nautilus_trader.live.config import LiveExecEngineConfig
from nautilus_trader.live.factories import LiveExecClientFactory
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import ExecAlgorithmId

from trading.adapters.dnse.config import DNSE_DATA_CLIENT_NAME
from trading.adapters.dnse.config import DnseDataClientConfig
from trading.adapters.dnse.data import build_bar_type_for_symbol
from trading.adapters.dnse.factory import DnseLiveDataClientFactory
from trading.adapters.entrade.config import DNSE_EXECUTION_CLIENT_NAME
from trading.adapters.entrade.config import EntradeExecClientConfig
from trading.adapters.entrade.factory import EntradeLiveExecClientFactory
from trading.adapters.entrade.transport import EntradeEnvironment
from trading.instruments import FuturesInstrumentSpec
from trading.config import ExecutionAlgorithmConfig


IMPORTABLE_ALPHA_STRATEGY_PATH = "trading.strategy:SystematicTradingStrategy"
IMPORTABLE_ALPHA_STRATEGY_CONFIG_PATH = (
    "trading.strategy:SystematicTradingStrategyConfig"
)
SANDBOX_CLIENT_NAME = "SANDBOX"


class ExecutionBroker(StrEnum):
    """Execution adapter selected by the NOX live composition."""

    SANDBOX = "sandbox"
    ENTRADE = "entrade"


class TradingEnvironment(StrEnum):
    """Broker environment selected by the NOX live composition."""

    DEMO = "demo"
    LIVE = "live"


@dataclass(frozen=True)
class TradingRuntimeConfig:
    """NOX composition config for a Nautilus TradingNode runtime."""

    api_key: str
    api_secret: str
    instrument_spec: FuturesInstrumentSpec
    alpha_path: str | None = None
    alphas: tuple[dict[str, Any], ...] = ()
    execution_broker: ExecutionBroker = ExecutionBroker.SANDBOX
    execution_environment: TradingEnvironment | None = None
    execution_algorithm: ExecutionAlgorithmConfig | None = None
    entrade_username: str | None = None
    entrade_password: str | None = None
    entrade_investor_id: int | str | None = None
    entrade_base_url: str = "https://services.entrade.com.vn"
    trader_id: str = "TRADER-001"
    bar_resolution: str = "1"
    capital: float = 1_000_000_000.0
    max_exposure_contracts: int | None = None
    oms_type: str = "NETTING"
    account_type: str = "MARGIN"
    margin_ratio: float | None = None
    bar_execution: bool = True
    trade_execution: bool = False
    use_dnse_working_dates: bool = True
    market_working_dates: tuple[str, ...] = ()
    close_positions_on_expiry_day: bool = True
    close_positions_on_stop: bool = True
    log_audit_events: bool = True
    ws_base_url: str = "wss://ws-openapi.dnse.com.vn"
    rest_base_url: str = "https://openapi.dnse.com.vn"
    historical_bar_type: str = "DERIVATIVE"
    log_level: str = "INFO"
    load_state: bool = False
    save_state: bool = False


def build_trading_node_config(config: TradingRuntimeConfig) -> TradingNodeConfig:
    if (config.alpha_path is None) == (not config.alphas):
        raise ValueError("Trading runtime requires exactly one alpha_path or alphas declaration")
    if (
        config.execution_broker == ExecutionBroker.ENTRADE
        and config.execution_environment == TradingEnvironment.LIVE
    ):
        raise RuntimeError(
            "Entrade live execution remains disabled until AR-001/F01-F04 "
            "broker validation is complete",
        )
    if config.execution_broker == ExecutionBroker.ENTRADE and (
        config.max_exposure_contracts is None or config.max_exposure_contracts < 1
    ):
        raise ValueError(
            "Entrade execution requires max_exposure_contracts of at least 1",
        )

    bar_type = build_bar_type_for_symbol(
        symbol=config.instrument_spec.symbol,
        resolution=config.bar_resolution,
        venue=config.instrument_spec.venue,
    )
    routing = RoutingConfig(default=True, venues=frozenset({config.instrument_spec.venue}))
    execution_algorithm = config.execution_algorithm
    strategy_config = ImportableStrategyConfig(
        strategy_path=IMPORTABLE_ALPHA_STRATEGY_PATH,
        config_path=IMPORTABLE_ALPHA_STRATEGY_CONFIG_PATH,
        config={
            "instrument_id": bar_type.instrument_id,
            "bar_type": bar_type,
            "capital": config.capital,
            "margin_ratio": config.margin_ratio,
            "close_positions_on_stop": config.close_positions_on_stop,
            "close_positions_on_expiry_day": config.close_positions_on_expiry_day,
            "market_working_dates": config.market_working_dates,
            "log_audit_events": config.log_audit_events,
            "log_events": False,
            "log_commands": False,
            "alpha_path": config.alpha_path,
            "alphas": config.alphas,
            "exec_algorithm_id": (
                ExecAlgorithmId(execution_algorithm.exec_algorithm_id)
                if execution_algorithm is not None
                else None
            ),
            "exec_algorithm_params": (
                execution_algorithm.order_params if execution_algorithm is not None else None
            ),
            "max_exposure_contracts": config.max_exposure_contracts,
            "require_monthly_contract": config.execution_broker == ExecutionBroker.ENTRADE,
            "warm_up_live_data": True,
        },
    )
    data_client_config = DnseDataClientConfig(
        api_key=config.api_key,
        api_secret=config.api_secret,
        instrument_spec=config.instrument_spec,
        rest_base_url=config.rest_base_url,
        ws_base_url=config.ws_base_url,
        use_dnse_working_dates=config.use_dnse_working_dates,
        market_working_dates=config.market_working_dates,
        historical_bar_type=config.historical_bar_type,
        routing=routing,
    )

    return TradingNodeConfig(
        trader_id=config.trader_id,
        logging=LoggingConfig(log_level=config.log_level, log_colors=False),
        data_engine=LiveDataEngineConfig(validate_data_sequence=True),
        exec_engine=LiveExecEngineConfig(
            reconciliation=config.execution_broker == ExecutionBroker.ENTRADE,
            snapshot_positions=True,
        ),
        load_state=config.load_state,
        save_state=config.save_state,
        strategies=[strategy_config],
        exec_algorithms=(
            [execution_algorithm.to_importable_config()] if execution_algorithm is not None else []
        ),
        data_clients={DNSE_DATA_CLIENT_NAME: data_client_config},
        exec_clients={_execution_client_name(config): _execution_client_config(config, routing)},
    )


def build_trading_node(
    config: TradingRuntimeConfig,
    data_client_factory: type[DnseLiveDataClientFactory] = DnseLiveDataClientFactory,
    loop: asyncio.AbstractEventLoop | None = None,
) -> TradingNode:
    node = TradingNode(config=build_trading_node_config(config), loop=loop)
    node.add_data_client_factory(DNSE_DATA_CLIENT_NAME, data_client_factory)
    node.add_exec_client_factory(_execution_client_name(config), _execution_client_factory(config))
    return node


def _execution_client_config(
    config: TradingRuntimeConfig,
    routing: RoutingConfig,
) -> LiveExecClientConfig:
    if config.execution_broker == ExecutionBroker.SANDBOX:
        if config.execution_environment is not None:
            raise ValueError("Sandbox execution does not accept a trading environment")
        return SandboxExecutionClientConfig(
            venue=config.instrument_spec.venue,
            starting_balances=[
                _format_starting_balance(config.capital, config.instrument_spec.currency_code),
            ],
            base_currency=config.instrument_spec.currency_code,
            oms_type=config.oms_type,
            account_type=config.account_type,
            bar_execution=config.bar_execution,
            trade_execution=config.trade_execution,
            routing=routing,
        )

    if config.execution_broker != ExecutionBroker.ENTRADE:
        raise ValueError(f"Unsupported execution broker: {config.execution_broker}")

    if config.execution_environment == TradingEnvironment.DEMO:
        environment = EntradeEnvironment.DEMO
    elif config.execution_environment == TradingEnvironment.LIVE:
        environment = EntradeEnvironment.LIVE
    else:
        raise ValueError("Entrade execution requires environment 'demo' or 'live'")

    return EntradeExecClientConfig(
        instrument_spec=config.instrument_spec,
        username=config.entrade_username,
        password=config.entrade_password,
        investor_id=config.entrade_investor_id,
        environment=environment,
        base_url=config.entrade_base_url,
        routing=routing,
    )


def _execution_client_factory(
    config: TradingRuntimeConfig,
) -> type[LiveExecClientFactory]:
    if config.execution_broker == ExecutionBroker.SANDBOX:
        return SandboxLiveExecClientFactory
    if config.execution_broker == ExecutionBroker.ENTRADE:
        return EntradeLiveExecClientFactory
    raise ValueError(f"Unsupported execution broker: {config.execution_broker}")


def _execution_client_name(config: TradingRuntimeConfig) -> str:
    if config.execution_broker == ExecutionBroker.SANDBOX:
        return SANDBOX_CLIENT_NAME
    if config.execution_broker == ExecutionBroker.ENTRADE:
        return DNSE_EXECUTION_CLIENT_NAME
    raise ValueError(f"Unsupported execution broker: {config.execution_broker}")


def _format_starting_balance(amount: float, currency_code: str) -> str:
    if float(amount).is_integer():
        amount_text = str(int(amount))
    else:
        amount_text = format(amount, "f").rstrip("0").rstrip(".")
    return f"{amount_text} {currency_code}"
