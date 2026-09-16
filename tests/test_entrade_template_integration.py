"""Integration tests for trading.adapters.entrade_template.

Skeleton ported from the NautilusTrader template integration suite
(python/tests/integration/test_python_adapter_template.py); bodies rewritten
for the DNSE data client and Entrade execution client with injected fakes so
the real LiveNode engines run without network access.
"""

from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from typing import Any

import pytest
from dnse.websocket.models import Ohlc

from nautilus_trader.common import Environment
from nautilus_trader.config import LiveNodeConfig
from nautilus_trader.core import UUID4
from nautilus_trader.live import LiveNode
from nautilus_trader.live.clients import DataClientFactory, ExecutionClientFactory
from nautilus_trader.model import (
    AccountId,
    ClientOrderId,
    ExecutionMassStatus,
    FillReport,
    InstrumentId,
    LiquiditySide,
    Money,
    OrderSide,
    OrderStatus,
    OrderStatusReport,
    OrderType,
    PositionSide,
    PositionStatusReport,
    Price,
    Quantity,
    TimeInForce,
    TradeId,
    TraderId,
    Venue,
    VenueOrderId,
)
from nautilus_trader.trading import Strategy

from trading.adapters.entrade_template.config import DnseDataClientConfig
from trading.adapters.entrade_template.config import EntradeExecClientConfig
from trading.adapters.entrade_template.constants import NOT_IMPLEMENTED
from trading.adapters.entrade_template.data import DnseLiveDataClient
from trading.adapters.entrade_template.data import build_bar_type_for_symbol
from trading.adapters.entrade_template.execution import EntradeExecutionClient
from trading.adapters.entrade_template.providers import DnseInstrumentProvider
from trading.adapters.entrade_template.providers import EntradeInstrumentProvider
from trading.instruments import FuturesInstrumentSpec

VENUE = "HNX"
DATA_SYMBOL = "VN30F1M"
CONTRACT_ID = InstrumentId.from_str("41I1G8000.HNX")

SPEC = FuturesInstrumentSpec(
    symbol=DATA_SYMBOL,
    venue=VENUE,
    underlying="VN30",
    currency_code="VND",
    currency_precision=0,
    currency_iso4217=704,
    currency_name="Vietnamese dong",
    price_precision=1,
    price_increment=0.1,
    multiplier=100_000,
    lot_size=1,
)

# 2025-01-02 02:00 UTC, a Thursday so the weekday gate lets the bar through.
BAR_TIME_SECONDS = 1_735_783_200


def _make_ohlc() -> Ohlc:
    return Ohlc.from_dict(
        {
            "symbol": DATA_SYMBOL,
            "resolution": "1",
            "open": 1000.0,
            "high": 1001.0,
            "low": 999.0,
            "close": 1000.5,
            "volume": 10,
            "time": BAR_TIME_SECONDS,
            "lastUpdated": BAR_TIME_SECONDS,
            "type": "history",
        },
    )


class FakeClock:
    def timestamp_ns(self) -> int:
        return 1_800_000_000_000_000_000


class FakeDnseTradingClient:
    """Emits one deterministic bar on every OHLC subscription."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.connected = False

    def on(self, event: str, handler: object) -> None:
        self.handlers[event] = handler

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def subscribe_ohlc_closed(self, **kwargs: object) -> None:
        on_ohlc = kwargs.get("on_ohlc")
        if on_ohlc is not None:
            on_ohlc(_make_ohlc())


class FakeDnseRestClient:
    def get_ohlc(self, **kwargs: object) -> tuple[int, dict]:
        return 200, {
            "t": [BAR_TIME_SECONDS],
            "o": [1000.0],
            "h": [1001.0],
            "l": [999.0],
            "c": [1000.5],
            "v": [10],
        }

    def get_working_dates(self, **kwargs: object) -> tuple[int, dict]:
        return 200, {"workingDates": ["2025-01-02"]}


class FakeEntradeClient:
    """Deterministic Entrade REST responses for one buy market order."""

    def __init__(self) -> None:
        self.order_payload = {
            "id": 7001,
            "symbol": "41I1G8000",
            "side": "NB",
            "price": 0.0,
            "quantity": 1,
            "orderType": "MAK",
            "orderStatus": "Filled",
            "fillQuantity": 1,
            "averagePrice": 1905.8,
            "tradingFee": 31_500.0,
            "tradingTax": 0.0,
            "reports": [
                {
                    "version": 1,
                    "execType": "F",
                    "lastQuantity": 1,
                    "lastPrice": 1905.8,
                    "modifiedDate": "2026-09-15T02:21:48.100Z",
                },
            ],
        }

    def authenticate(self, username: str, password: str) -> str:
        return "test-token"

    def get_account_balance(self, investor_id: int | str) -> dict:
        return {
            "investorAccountId": 456,
            "nav": 100_000_000,
            "availableCash": 90_000_000,
        }

    def list_margin_portfolios(self, investor_id: int | str) -> dict:
        return {"data": [{"id": 32}]}

    def list_derivatives(self) -> dict:
        return {
            "data": [
                {
                    "symbol": "41I1G8000",
                    "type": "VN30F2M",
                    "expirationDate": "2027-08-20T00:00:00.000Z",
                    "marketPrice": 1535.2,
                },
            ],
        }

    def get_buying_power(self, **kwargs: object) -> dict:
        return {"qmax": 10}

    def place_order(self, **kwargs: object) -> dict:
        return self.order_payload

    def get_order(self, order_id: int | str) -> dict:
        return self.order_payload

    def list_orders(self, **kwargs: object) -> dict:
        return {"data": []}

    def list_deals(self, **kwargs: object) -> dict:
        return {"data": []}

    def close(self) -> None:
        return None


def _build_factories(
    trading: FakeDnseTradingClient,
    rest: FakeDnseRestClient,
    api: FakeEntradeClient,
) -> tuple[type[DataClientFactory], type[ExecutionClientFactory]]:
    class TestDataFactory(DataClientFactory):
        @staticmethod
        def create(*, name: str, config, cache, clock):
            provider = DnseInstrumentProvider(config, clock)
            return DnseLiveDataClient(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                venue=config.venue,
                instrument_provider=provider,
                trading_client=trading,
                rest_client=rest,
            )

    class TestExecFactory(ExecutionClientFactory):
        @staticmethod
        def create(*, name: str, config, cache, clock, trader_id):
            provider = EntradeInstrumentProvider(
                api,
                config.instrument_spec,
                config.instrument_provider,
                clock=clock,
            )
            return EntradeExecutionClient(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                trader_id=trader_id,
                instrument_provider=provider,
                client=api,
            )

    return TestDataFactory, TestExecFactory


class LifecycleStrategy(Strategy):
    """Subscribe bars, submit one DAY limit order on the first bar, stop on fill."""

    def __init__(self, contract_id: InstrumentId) -> None:
        super().__init__()
        self._contract_id = contract_id
        self.bar: Any = None
        self.order: Any = None
        self.fill: Any = None

    def on_start(self) -> None:
        self.subscribe_bars(build_bar_type_for_symbol(DATA_SYMBOL, "1", VENUE))

    def on_bar(self, bar) -> None:
        if self.bar is None:
            self.bar = bar
            self.order = self.order_factory.limit(
                self._contract_id,
                OrderSide.BUY,
                Quantity.from_int(1),
                price=Price.from_str("1905.8"),
                time_in_force=TimeInForce.DAY,
            )
            self.submit_order(self.order)

    def on_order_denied(self, event) -> None:
        self.shutdown_system("Order denied; ending the lifecycle run")

    def on_order_filled(self, event) -> None:
        self.fill = event
        self.shutdown_system("Entrade template order filled")


def build_node() -> tuple[LiveNode, LifecycleStrategy]:
    trading = FakeDnseTradingClient()
    rest = FakeDnseRestClient()
    api = FakeEntradeClient()
    data_factory, exec_factory = _build_factories(trading, rest, api)

    node = LiveNode.build(
        "ENTRADE-TEMPLATE",
        LiveNodeConfig(
            environment=Environment.SANDBOX,
            trader_id=TraderId("TRADER-001"),
            timeout_connection_secs=2,
            timeout_reconciliation_secs=2,
            timeout_portfolio_secs=2,
            timeout_disconnection_secs=1,
            delay_post_stop_secs=0,
            data_clients={
                "DNSE": DnseDataClientConfig(
                    api_key="key",
                    api_secret="secret",
                    instrument_spec=SPEC,
                    historical_source="api",
                ),
            },
            exec_clients={
                "DNSE": EntradeExecClientConfig(
                    instrument_spec=SPEC,
                    username="user",
                    password="password",
                    investor_id=123,
                    account_id="DNSE-456",
                ),
            },
        ),
        data_factories={"DNSE": data_factory},
        exec_factories={"DNSE": exec_factory},
    )
    strategy = LifecycleStrategy(CONTRACT_ID)
    node.add_strategy(strategy)
    return node, strategy


async def run_hosted(node: LiveNode) -> None:
    async with asyncio.timeout(10):
        await node.run_async()


@pytest.mark.parametrize(
    "client_type",
    [DnseLiveDataClient, EntradeExecutionClient],
)
def test_clients_declare_all_client_hooks(client_type) -> None:
    """Keep every adapter hook visible with compatible parameter names."""
    base_type = client_type.__bases__[0]
    hooks = {
        name: method
        for name, method in inspect.getmembers(base_type)
        if inspect.iscoroutinefunction(method)
        or name
        in {
            "_handles_order_venue",
            "_provides_bulk_position_coverage",
            "_calculate_commission",
        }
    }

    assert hooks.keys() <= client_type.__dict__.keys()
    for name, method in hooks.items():
        assert list(inspect.signature(client_type.__dict__[name]).parameters) == list(
            inspect.signature(method).parameters,
        ), name


def test_providers_declare_instrument_loading_hooks() -> None:
    """Expose the venue instrument-loading entry points on both providers."""
    assert {"load_all_async", "load_ids_async"} <= (
        DnseInstrumentProvider.__dict__.keys()
    )
    assert {"load_all_async", "load_ids_async"} <= (
        EntradeInstrumentProvider.__dict__.keys()
    )


@pytest.mark.parametrize(
    ("client_type", "method"),
    [
        (DnseLiveDataClient, "_request_trades"),
        (EntradeExecutionClient, "_query_order"),
    ],
)
def test_unsupported_hooks_report_consistent_error(client_type, method) -> None:
    """Unsupported operations fail explicitly rather than reporting success."""
    with pytest.raises(NotImplementedError) as exc_info:
        asyncio.run(getattr(client_type, method)(object(), object()))

    assert str(exc_info.value) == NOT_IMPLEMENTED


@pytest.mark.parametrize("launch", ["owned", "hosted", "uvloop"])
def test_adapter_runs_through_live_engines(launch) -> None:
    """The full bar → order → fill lifecycle flows through the real engines."""
    runner = pytest.importorskip("uvloop").run if launch == "uvloop" else asyncio.run
    node, strategy = build_node()
    if launch == "owned":
        node.run()
    else:
        runner(run_hosted(node))

    assert strategy.bar is not None
    assert strategy.bar.close == Price(1000.5, 1)
    assert strategy.fill.trader_id == TraderId("TRADER-001")
    assert strategy.fill.account_id == AccountId("DNSE-456")
    assert strategy.fill.strategy_id == strategy.strategy_id
    assert strategy.fill.instrument_id == CONTRACT_ID
    assert strategy.fill.order_side == OrderSide.BUY
    assert strategy.fill.last_qty == Quantity.from_int(1)
    assert strategy.fill.last_px == Price.from_str("1905.8")
    assert node.cache.order(strategy.order.client_order_id).status == OrderStatus.FILLED


@pytest.mark.parametrize(
    "kind",
    ["order", "fill", "position", "mass_order", "mass_fill", "mass_position", "mass_venue"],
)
def test_execution_output_rejects_foreign_report_identity(kind) -> None:
    """Execution output rejects reports whose identity does not match the client."""
    errors: list[str] = []
    trading = FakeDnseTradingClient()
    rest = FakeDnseRestClient()
    api = FakeEntradeClient()

    class Client(EntradeExecutionClient):
        async def _connect(self) -> None:
            await super()._connect()

            if kind.endswith("order"):
                report = _foreign_order_status_report(CONTRACT_ID)
            elif kind.endswith("fill"):
                report = _foreign_fill_report(CONTRACT_ID)
            elif kind.endswith("position"):
                report = _foreign_position_status_report(CONTRACT_ID)
            if kind.startswith("mass_"):
                mass = ExecutionMassStatus(
                    self.client_id,
                    self.account_id,
                    Venue("FOREIGN") if kind == "mass_venue" else Venue(VENUE),
                    41,
                )
                if kind != "mass_venue":
                    getattr(mass, f"add_{kind.removeprefix('mass_')}_reports")([report])
                report = mass
            try:
                self._handle_report(report)
            except TypeError as e:
                errors.append(str(e))

    class Factory(ExecutionClientFactory):
        @staticmethod
        def create(*, name: str, config, cache, clock, trader_id):
            provider = EntradeInstrumentProvider(
                api,
                config.instrument_spec,
                config.instrument_provider,
                clock=clock,
            )
            return Client(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                trader_id=trader_id,
                instrument_provider=provider,
                client=api,
            )

    data_factory, _ = _build_factories(trading, rest, api)
    node = LiveNode.build(
        "ENTRADE-TEMPLATE",
        LiveNodeConfig(
            environment=Environment.SANDBOX,
            trader_id=TraderId("TRADER-001"),
            timeout_connection_secs=2,
            timeout_reconciliation_secs=2,
            timeout_portfolio_secs=2,
            timeout_disconnection_secs=1,
            delay_post_stop_secs=0,
            data_clients={
                "DNSE": DnseDataClientConfig(
                    api_key="key",
                    api_secret="secret",
                    instrument_spec=SPEC,
                    historical_source="api",
                ),
            },
            exec_clients={
                "DNSE": EntradeExecClientConfig(
                    instrument_spec=SPEC,
                    username="user",
                    password="password",
                    investor_id=123,
                    account_id="DNSE-456",
                ),
            },
        ),
        data_factories={"DNSE": data_factory},
        exec_factories={"DNSE": Factory},
    )
    strategy = LifecycleStrategy(CONTRACT_ID)
    node.add_strategy(strategy)
    asyncio.run(run_hosted(node))

    assert errors == ["Execution output identity does not match its owner"]
    assert strategy.fill.last_qty == Quantity.from_int(1)


def _foreign_order_status_report(instrument_id: InstrumentId) -> OrderStatusReport:
    return OrderStatusReport(
        account_id=AccountId("SIM-001"),
        instrument_id=instrument_id,
        venue_order_id=VenueOrderId("1"),
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        order_status=OrderStatus.ACCEPTED,
        quantity=Quantity.from_int(1),
        filled_qty=Quantity.from_int(0),
        ts_accepted=10,
        ts_last=20,
        ts_init=30,
    )


def _foreign_fill_report(instrument_id: InstrumentId) -> FillReport:
    return FillReport(
        account_id=AccountId("SIM-001"),
        instrument_id=instrument_id,
        venue_order_id=VenueOrderId("1"),
        trade_id=TradeId("T-1"),
        order_side=OrderSide.BUY,
        last_qty=Quantity.from_int(1),
        last_px=Price.from_str("1905.8"),
        commission=Money(31_500, _vnd_currency()),
        liquidity_side=LiquiditySide.TAKER,
        ts_event=10,
        ts_init=11,
        client_order_id=ClientOrderId("O-1"),
    )


def _foreign_position_status_report(instrument_id: InstrumentId) -> PositionStatusReport:
    return PositionStatusReport(
        account_id=AccountId("SIM-001"),
        instrument_id=instrument_id,
        position_side=PositionSide.LONG,
        quantity=Quantity.from_int(1),
        ts_last=10,
        ts_init=20,
        report_id=UUID4(),
    )


def _vnd_currency():
    from nautilus_trader.model import Currency, CurrencyType

    return Currency(
        "VND",
        0,
        704,
        "Vietnamese dong",
        CurrencyType.FIAT,
    )
