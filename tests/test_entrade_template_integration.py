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
    ClientId,
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
    StrategyId,
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
from market_data.instruments import FuturesInstrumentSpec

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


def build_node(
    exec_factory: type[ExecutionClientFactory] | None = None,
    strategy: Strategy | None = None,
    delay_post_stop_secs: int = 0,
) -> tuple[LiveNode, Any]:
    trading = FakeDnseTradingClient()
    rest = FakeDnseRestClient()
    api = FakeEntradeClient()
    data_factory, default_exec_factory = _build_factories(trading, rest, api)

    node = LiveNode.build(
        "ENTRADE-TEMPLATE",
        LiveNodeConfig(
            environment=Environment.SANDBOX,
            trader_id=TraderId("TRADER-001"),
            timeout_connection_secs=2,
            timeout_reconciliation_secs=2,
            timeout_portfolio_secs=2,
            timeout_disconnection_secs=1,
            delay_post_stop_secs=delay_post_stop_secs,
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
        exec_factories={"DNSE": exec_factory or default_exec_factory},
    )
    strategy = strategy or LifecycleStrategy(CONTRACT_ID)
    node.add_strategy(strategy)
    return node, strategy


def make_exec_factory(
    client_cls: type[EntradeExecutionClient],
    api: FakeEntradeClient | None = None,
    clients: list | None = None,
) -> type[ExecutionClientFactory]:
    """Build an execution factory constructing ``client_cls`` with the fake API."""

    api = api or FakeEntradeClient()

    class Factory(ExecutionClientFactory):
        @staticmethod
        def create(*, name: str, config, cache, clock, trader_id):
            provider = EntradeInstrumentProvider(
                api,
                config.instrument_spec,
                config.instrument_provider,
                clock=clock,
            )
            client = client_cls(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                trader_id=trader_id,
                instrument_provider=provider,
                client=api,
            )
            if clients is not None:
                clients.append(client)
            return client

    return Factory


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


# --- Ports of the remaining NautilusTrader template integration cases ---


@pytest.mark.parametrize("shutdown_cancel", [False, True])
def test_order_list_batch_fields_and_shutdown_cancellation(shutdown_cancel) -> None:
    """Preserve batch fields and accept cancellations during the stop grace period."""
    submitted = []
    modified = []
    canceled = []
    queried = []
    client_id = ClientId("DNSE")
    params = {"batch": "ordered", "sequence": 71}

    class Client(EntradeExecutionClient):
        async def _submit_order_list(self, command):
            submitted.append(command)
            for initialized in command.order_inits:
                order = self.cache.order(initialized.client_order_id)
                self.generate_order_submitted(order)
                self.generate_order_accepted(
                    order,
                    VenueOrderId(str(order.client_order_id)),
                    self.clock.timestamp_ns(),
                )

        async def _modify_order(self, command):
            modified.append(command)
            order = self.cache.order(command.client_order_id)
            self.generate_order_updated(
                order,
                order.venue_order_id,
                command.quantity,
                command.price,
                command.trigger_price,
                None,
                self.clock.timestamp_ns(),
            )

        async def _cancel_order(self, command):
            canceled.append(command)
            order = self.cache.order(command.client_order_id)
            self.generate_order_canceled(order, order.venue_order_id, self.clock.timestamp_ns())

        async def _query_account(self, command):
            queried.append(command)

        async def _query_order(self, command):
            queried.append(command)

    class Consumer(Strategy):
        def on_start(self):
            self.orders = [
                self.order_factory.limit(
                    CONTRACT_ID,
                    OrderSide.BUY,
                    Quantity.from_str(qty),
                    Price.from_str(px),
                    time_in_force=TimeInForce.DAY,
                )
                for qty, px in [("7", "1905.8"), ("11", "1906.0")]
            ]
            self.accepted = 0
            self.updated = 0
            self.canceled = 0
            self.submit_order_list(self.orders, client_id=client_id, params=params)

        def on_order_accepted(self, event):  # noqa: ARG002 - Retain the strategy callback signature.
            self.accepted += 1
            if self.accepted != 2:
                return
            if shutdown_cancel:
                self.shutdown_system("Cancel during grace period")
            else:
                self.modify_orders(
                    [
                        (
                            self.orders[0].client_order_id,
                            Quantity.from_str("31"),
                            Price.from_str("1910.7"),
                            None,
                        ),
                        (
                            self.orders[1].client_order_id,
                            Quantity.from_str("47"),
                            Price.from_str("1920.9"),
                            None,
                        ),
                    ],
                    client_id=client_id,
                    params=params,
                )

        def on_order_updated(self, event):  # noqa: ARG002 - Retain the strategy callback signature.
            self.updated += 1
            if self.updated == 2:
                self.query_account(AccountId("DNSE-456"), client_id=client_id, params=params)
                self.query_order(self.orders[0], client_id=client_id, params=params)
                self.cancel_orders(
                    [o.client_order_id for o in self.orders],
                    client_id=client_id,
                    params=params,
                )

        def on_order_canceled(self, event):  # noqa: ARG002 - Retain the strategy callback signature.
            self.canceled += 1
            if self.canceled == 2:
                self.shutdown_system("Batch canceled")

        def on_stop(self):
            if shutdown_cancel:
                self.cancel_orders(
                    [o.client_order_id for o in self.orders],
                    client_id=client_id,
                    params=params,
                )

    consumer = Consumer()
    node, _ = build_node(
        exec_factory=make_exec_factory(Client),
        strategy=consumer,
        delay_post_stop_secs=1 if shutdown_cancel else 0,
    )
    asyncio.run(run_hosted(node))

    ids = [order.client_order_id for order in consumer.orders]
    assert len(submitted) == 1
    command = submitted[0]
    assert command.trader_id == TraderId("TRADER-001")
    assert command.client_id == client_id
    assert command.strategy_id == consumer.strategy_id
    assert command.instrument_id == CONTRACT_ID
    assert command.order_list.client_order_ids() == ids
    assert [order.client_order_id for order in command.order_inits] == ids
    assert [order.quantity for order in command.order_inits] == [
        Quantity.from_str("7"),
        Quantity.from_str("11"),
    ]
    assert command.params == params
    assert command.position_id is None
    assert command.exec_algorithm_id is None
    assert [command.client_order_id for command in canceled] == ids
    assert [command.venue_order_id for command in canceled] == [
        VenueOrderId(str(value)) for value in ids
    ]
    assert [command.params for command in canceled] == [params, params]
    assert [node.cache.order(value).status for value in ids] == [
        OrderStatus.CANCELED,
        OrderStatus.CANCELED,
    ]

    if shutdown_cancel:
        assert modified == []
        assert queried == []
    else:
        assert [command.client_order_id for command in modified] == ids
        assert [command.quantity for command in modified] == [
            Quantity.from_str("31"),
            Quantity.from_str("47"),
        ]
        assert [command.price for command in modified] == [
            Price.from_str("1910.7"),
            Price.from_str("1920.9"),
        ]
        assert [command.params for command in modified] == [params, params]
        assert [command.params for command in queried] == [params, params]
        assert queried[0].account_id == AccountId("DNSE-456")
        assert queried[1].client_order_id == ids[0]


@pytest.mark.parametrize("source", ["orders", "fills", "positions", "mass"])
def test_reconciliation_rejects_foreign_returned_reports(source) -> None:
    """Reconciliation rejects foreign returned reports."""
    clients = []

    class Client(EntradeExecutionClient):
        async def _generate_mass_status(self, lookback_mins):
            if source != "mass":
                return await super()._generate_mass_status(lookback_mins)
            report = ExecutionMassStatus(self.client_id, self.account_id, Venue(VENUE), 47)
            report.add_position_reports([_foreign_position_status_report(CONTRACT_ID)])
            return report

        async def _generate_order_status_reports(self, _command):
            return (
                [_foreign_order_status_report(CONTRACT_ID)]
                if source == "orders"
                else []
            )

        async def _generate_fill_reports(self, _command):
            return [_foreign_fill_report(CONTRACT_ID)] if source == "fills" else []

        async def _generate_position_status_reports(self, _command):
            return (
                [_foreign_position_status_report(CONTRACT_ID)]
                if source == "positions"
                else []
            )

    node, strategy = build_node(exec_factory=make_exec_factory(Client, clients=clients))
    with pytest.raises(RuntimeError, match="Failed to get mass status from DNSE"):
        asyncio.run(run_hosted(node))

    assert strategy.fill is None
    assert clients[0]._runtime.complete is True
    with pytest.raises(RuntimeError, match="disposed"):
        clients[0].cache.instrument(CONTRACT_ID)


def test_reconciliation_calls_external_order_and_commission_hooks() -> None:
    """Reconciliation calls external order and commission hooks."""
    commissions = []
    registrations = []
    instruments = []
    external_id = VenueOrderId("EXTERNAL-101")

    class Client(EntradeExecutionClient):
        async def _on_instrument(self, instrument):
            instruments.append((instrument, self.cache.instrument(instrument.id)))

        async def _generate_order_status_reports(self, _command):
            now = self.clock.timestamp_ns()
            return [
                OrderStatusReport(
                    self.account_id,
                    CONTRACT_ID,
                    external_id,
                    OrderSide.BUY,
                    OrderType.MARKET,
                    TimeInForce.GTC,
                    OrderStatus.FILLED,
                    Quantity.from_str("3"),
                    Quantity.from_str("3"),
                    now - 3,
                    now - 2,
                    now,
                    avg_px=Decimal("1905.8"),
                ),
            ]

        async def _generate_position_status_reports(self, _command):
            now = self.clock.timestamp_ns()
            return [
                PositionStatusReport(
                    self.account_id,
                    CONTRACT_ID,
                    PositionSide.LONG,
                    Quantity.from_str("3"),
                    now - 1,
                    now,
                ),
            ]

        def _calculate_commission(self, instrument, last_qty, last_px, liquidity_side):
            commissions.append((instrument, last_qty, last_px, liquidity_side))
            return Money(31_500, _vnd_currency())

        async def _register_external_order(
            self,
            client_order_id,
            venue_order_id,
            instrument_id,
            strategy_id,
            ts_init,
        ):
            registrations.append(
                (client_order_id, venue_order_id, instrument_id, strategy_id, ts_init),
            )

    node, strategy = build_node(exec_factory=make_exec_factory(Client))
    asyncio.run(run_hosted(node))

    instrument = node.cache.instrument(CONTRACT_ID)
    external_order = node.cache.order(node.cache.client_order_id(external_id))
    # Our venue publishes the continuous symbol plus monthly contracts; the
    # hook must see each one with a cache that already holds the instrument.
    contract_pair = next(pair for pair in instruments if pair[0].id == CONTRACT_ID)
    assert contract_pair == (instrument, instrument)
    assert commissions == [
        (instrument, Quantity.from_str("3"), Price.from_str("1905.8"), LiquiditySide.TAKER),
    ]
    assert registrations == [
        (
            external_order.client_order_id,
            external_id,
            CONTRACT_ID,
            StrategyId("EXTERNAL"),
            external_order.last_event.ts_init,
        ),
    ]
    assert external_order.status == OrderStatus.FILLED
    assert external_order.last_event.commission == Money(31_500, _vnd_currency())
    assert strategy.fill.last_qty == Quantity.from_int(1)


@pytest.mark.parametrize(
    ("kind", "expected_status"),
    [
        ("denied", OrderStatus.DENIED),
        ("rejected", OrderStatus.REJECTED),
        ("modify_rejected", OrderStatus.ACCEPTED),
        ("cancel_rejected", OrderStatus.ACCEPTED),
        ("triggered", OrderStatus.TRIGGERED),
        ("expired", OrderStatus.EXPIRED),
    ],
)
def test_execution_generated_event_reaches_core_and_strategy(kind, expected_status) -> None:
    """Generated events preserve their fields and apply the corresponding core transition."""
    emitted = []
    received = []
    venue_order_id = VenueOrderId("VENUE-173")
    reason = "Distinct venue rejection reason"
    event_ns = 1704164646000000037

    class Client(EntradeExecutionClient):
        async def _submit_order(self, command):
            order = command.order
            if kind == "denied":
                self.generate_order_denied(order, reason)
                return
            self.generate_order_submitted(order)
            if kind == "rejected":
                self.generate_order_rejected(order, reason, event_ns, due_post_only=True)
            else:
                self.generate_order_accepted(order, venue_order_id, event_ns - 11)
                if not kind.endswith("rejected"):
                    getattr(self, f"generate_order_{kind}")(order, venue_order_id, event_ns)

        async def _modify_order(self, command):
            self.generate_order_modify_rejected(
                self.cache.order(command.client_order_id),
                venue_order_id,
                reason,
                event_ns,
            )

        async def _cancel_order(self, command):
            self.generate_order_cancel_rejected(
                self.cache.order(command.client_order_id),
                venue_order_id,
                reason,
                event_ns,
            )

    class Consumer(Strategy):
        def on_start(self):
            self.order = self.order_factory.stop_limit(
                CONTRACT_ID,
                OrderSide.BUY,
                Quantity.from_str("17"),
                Price.from_str("1906.1"),
                Price.from_str("1905.9"),
            )
            self.submit_order(self.order)

        def on_order_accepted(self, event):  # noqa: ARG002 - Preserve the strategy callback signature.
            if kind == "modify_rejected":
                self.modify_order(self.order.client_order_id, quantity=Quantity.from_str("23"))
            elif kind == "cancel_rejected":
                self.cancel_order(self.order.client_order_id)

    def record(self, event):
        received.append(event)
        self.shutdown_system("Generated event received")

    setattr(Consumer, f"on_order_{kind}", record)
    consumer = Consumer()
    node, _ = build_node(exec_factory=make_exec_factory(Client, clients=emitted), strategy=consumer)
    asyncio.run(run_hosted(node))

    assert len(received) == 1
    event = received[0]
    assert event.trader_id == TraderId("TRADER-001")
    assert event.strategy_id == consumer.strategy_id
    assert event.instrument_id == CONTRACT_ID
    assert event.client_order_id == consumer.order.client_order_id
    if kind != "denied":
        assert event.reconciliation is False
    if kind == "denied":
        assert event.ts_event == event.ts_init
    else:
        assert event.account_id == AccountId("DNSE-456")
        assert event.ts_event == event_ns
    if kind in ("denied", "rejected", "modify_rejected", "cancel_rejected"):
        assert event.reason == reason
    if kind == "rejected":
        assert event.due_post_only is True
    if kind not in ("denied", "rejected"):
        assert event.venue_order_id == venue_order_id
    assert node.cache.order(consumer.order.client_order_id).status == expected_status
    assert emitted[0].is_connected is False


def test_adapter_cache_queries_follow_core_order_and_position_states(monkeypatch) -> None:
    """Return filtered, owned cache snapshots at each order transition."""
    from nautilus_trader.model import ClientOrderId as Coid
    from nautilus_trader.model import InstrumentId as Iid
    from nautilus_trader.model import OrderListId
    from nautilus_trader.model import PositionId

    clients = []
    snapshots = []
    original_fill = LifecycleStrategy.on_order_filled

    class Client(EntradeExecutionClient):
        pass

    def capture(self, event):
        cache = clients[0].cache
        order_id = event.client_order_id
        filters = {
            "venue": Venue(VENUE),
            "instrument_id": CONTRACT_ID,
            "strategy_id": self.strategy_id,
            "account_id": AccountId("DNSE-456"),
        }
        mismatches = {
            "venue": Venue("OTHER"),
            "instrument_id": Iid.from_str("XXZZ99.OTHER"),
            "strategy_id": StrategyId("OTHER-001"),
            "account_id": AccountId("OTHER-001"),
            "side": OrderSide.SELL,
        }
        collections = {}

        for method in ("orders", "orders_open", "orders_inflight"):
            query = getattr(cache, method)
            collections[method] = [o.client_order_id for o in query(**filters, side=OrderSide.BUY)]
            collections[f"{method}:unfiltered"] = [o.client_order_id for o in query()]
            for field, value in mismatches.items():
                collections[f"{method}:{field}"] = query(**{**filters, field: value})
        positions = cache.positions_open(**filters, side=PositionSide.LONG)
        position_misses = {}
        for field, value in {**mismatches, "side": PositionSide.SHORT}.items():
            position_misses[field] = cache.positions_open(**{**filters, field: value})
        snapshots.append(
            {
                "type": type(event).__name__,
                "order": cache.order(order_id),
                "collections": collections,
                "count": cache.orders_open_count(**filters, side=OrderSide.BUY),
                "count_wrong_side": cache.orders_open_count(**filters, side=OrderSide.SELL),
                "open_ids": cache.client_order_ids_open(**filters),
                "wrong_open_ids": cache.client_order_ids_open(venue=Venue("OTHER")),
                "positions": positions,
                "position_misses": position_misses,
                "position_id": cache.position_id(order_id),
                "position": cache.position(positions[0].id) if positions else None,
                "venue_order_id": cache.venue_order_id(order_id),
                "client_order_id": cache.client_order_id(event.venue_order_id)
                if hasattr(event, "venue_order_id")
                else None,
                "strategy_id": cache.strategy_id_for_order(order_id),
                "account": cache.account(AccountId("DNSE-456")),
                "instrument_ids": cache.instrument_ids(Venue(VENUE)),
                "instruments": cache.instruments(Venue(VENUE)),
                "foreign_instruments": cache.instruments(Venue("OTHER")),
                "foreign_ids": cache.instrument_ids(Venue("OTHER")),
                "missing": [
                    cache.get("absent"),
                    cache.order(Coid("absent")),
                    cache.account(AccountId("OTHER-001")),
                    cache.position(PositionId("absent")),
                    cache.order_list(OrderListId("absent")),
                    cache.order_book(CONTRACT_ID),
                    cache.quote(CONTRACT_ID, 1),
                    cache.instrument(Iid.from_str("XXZZ99.OTHER")),
                    cache.client_order_id(VenueOrderId("absent")),
                    cache.venue_order_id(Coid("absent")),
                    cache.position_id(Coid("absent")),
                    cache.strategy_id_for_order(Coid("absent")),
                ],
            },
        )

        if type(event).__name__ == "OrderFilled":
            original_fill(self, event)

    for event in ("submitted", "accepted", "filled"):
        monkeypatch.setattr(LifecycleStrategy, f"on_order_{event}", capture)
    node, strategy = build_node(exec_factory=make_exec_factory(Client, clients=clients))
    asyncio.run(run_hosted(node))

    assert [snapshot["type"] for snapshot in snapshots] == [
        "OrderSubmitted",
        "OrderAccepted",
        "OrderFilled",
    ]

    for snapshot, status in zip(
        snapshots,
        [OrderStatus.SUBMITTED, OrderStatus.ACCEPTED, OrderStatus.FILLED],
        strict=True,
    ):
        assert snapshot["order"].status == status
        assert snapshot["order"].client_order_id == strategy.order.client_order_id
        assert snapshot["collections"]["orders"] == [strategy.order.client_order_id]
        assert snapshot["collections"]["orders:unfiltered"] == [strategy.order.client_order_id]

        for method, expected in (
            ("orders_open", status == OrderStatus.ACCEPTED),
            ("orders_inflight", status == OrderStatus.SUBMITTED),
        ):
            ids = [strategy.order.client_order_id] if expected else []
            assert snapshot["collections"][method] == ids
            assert snapshot["collections"][f"{method}:unfiltered"] == ids
        assert all(
            value == []
            for key, value in snapshot["collections"].items()
            if ":" in key and not key.endswith(":unfiltered")
        )
        assert snapshot["count"] == (1 if status == OrderStatus.ACCEPTED else 0)
        assert snapshot["count_wrong_side"] == 0
        assert snapshot["open_ids"] == (
            [strategy.order.client_order_id] if status == OrderStatus.ACCEPTED else []
        )
        assert snapshot["wrong_open_ids"] == []
        assert snapshot["strategy_id"] == strategy.strategy_id
        assert snapshot["account"].id == AccountId("DNSE-456")
        assert CONTRACT_ID in snapshot["instrument_ids"]
        assert CONTRACT_ID in [instrument.id for instrument in snapshot["instruments"]]
        assert snapshot["foreign_instruments"] == []
        assert snapshot["foreign_ids"] == []
        assert snapshot["missing"] == [None] * 12
        assert snapshot["position_misses"] == {
            field: [] for field in ("venue", "instrument_id", "strategy_id", "account_id", "side")
        }

        if status == OrderStatus.FILLED:
            assert [position.id for position in snapshot["positions"]] == [
                strategy.fill.position_id,
            ]
            assert snapshot["position"].quantity == Quantity.from_int(1)
            assert snapshot["position_id"] == strategy.fill.position_id
        else:
            assert snapshot["positions"] == []
            assert snapshot["position"] is None
        assert snapshot["venue_order_id"] == (
            None if status == OrderStatus.SUBMITTED else strategy.fill.venue_order_id
        )
        assert snapshot["client_order_id"] == (
            None if status == OrderStatus.SUBMITTED else strategy.order.client_order_id
        )


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("trader", "Execution client trader identity does not match its node"),
        ("tolerance", "Position reconciliation tolerance must be nonnegative"),
        ("venue", "Execution clients require a venue"),
    ],
)
def test_execution_factory_rejects_invalid_identity_and_tolerance(kind, message) -> None:
    """Invalid execution identities fail before an adapter can enter the core."""
    from trading.adapters.entrade_template.factories import EntradeLiveExecClientFactory

    clients = []

    class InvalidFactory(EntradeLiveExecClientFactory):
        @staticmethod
        def create(**kwargs: object) -> object:
            client = EntradeLiveExecClientFactory.create(**kwargs)
            if kind == "trader":
                client.trader_id = TraderId("OTHER-001")
            elif kind == "tolerance":
                client.position_reconciliation_tolerance = Decimal("-0.00000001")
            else:
                client.venue = None
            clients.append(client)
            return client

    with pytest.raises(RuntimeError, match=message):
        build_node(exec_factory=InvalidFactory)

    assert len(clients) == 1
    with pytest.raises(RuntimeError, match="disposed"):
        clients[0].cache.instrument(CONTRACT_ID)


@pytest.mark.parametrize(
    "kind",
    ["unknown", "fills_without_order", "foreign_associated_fill", "foreign_event"],
)
def test_execution_output_rejects_invalid_payload_before_core_dispatch(kind) -> None:
    """Invalid report combinations and foreign events never reach core processing."""
    from nautilus_trader.core import UUID4 as Uuid4
    from nautilus_trader.model import OrderSubmitted

    rejected = []

    class Client(EntradeExecutionClient):
        async def _connect(self):
            await super()._connect()

            if kind == "unknown":
                with pytest.raises(TypeError, match="Expected a Nautilus execution report"):
                    self._handle_report(object())
            elif kind == "fills_without_order":
                with pytest.raises(
                    TypeError,
                    match="Associated fills require an OrderStatusReport",
                ):
                    self._handle_report(_foreign_position_status_report(CONTRACT_ID), [])
            elif kind == "foreign_associated_fill":
                report = _foreign_order_status_report(CONTRACT_ID)
                # Preserve valid outer identity so the associated fill determines rejection.
                values = report.to_dict()
                values["account_id"] = str(self.account_id)
                report = OrderStatusReport.from_dict(values)
                with pytest.raises(
                    TypeError,
                    match="Execution output identity does not match its owner",
                ):
                    self._handle_report(report, [_foreign_fill_report(CONTRACT_ID)])
            else:
                event = OrderSubmitted(
                    TraderId("OTHER-001"),
                    StrategyId("OTHER-002"),
                    CONTRACT_ID,
                    ClientOrderId("OTHER-3"),
                    self.account_id,
                    Uuid4(),
                    149,
                    151,
                )
                with pytest.raises(
                    TypeError,
                    match="Execution output identity does not match its owner",
                ):
                    self._handle_event(event)
            rejected.append(kind)

    node, strategy = build_node(exec_factory=make_exec_factory(Client))
    asyncio.run(run_hosted(node))

    assert rejected == [kind]
    assert strategy.fill.last_qty == Quantity.from_int(1)
    assert node.cache.order(strategy.order.client_order_id).status == OrderStatus.FILLED


@pytest.mark.parametrize("output", ["generated", "event", "batch"])
def test_cancel_all_orders_preserves_filter_and_cancels_core_order(output) -> None:
    """Bulk cancellation forwards the strategy, side, and params to the custom client."""
    from nautilus_trader.core import UUID4 as Uuid4
    from nautilus_trader.model import OrderAccepted
    from nautilus_trader.model import OrderCanceled
    from nautilus_trader.model import OrderSubmitted

    commands = []
    received = []
    params = {"reason": "session_end", "sequence": 179}

    class Client(EntradeExecutionClient):
        async def _submit_order(self, command):
            if output == "generated":
                self.generate_order_submitted(command.order)
                self.generate_order_accepted(command.order, VenueOrderId("CANCEL-181"), 191)
            else:
                submitted = OrderSubmitted(
                    self.trader_id,
                    command.strategy_id,
                    command.instrument_id,
                    command.client_order_id,
                    self.account_id,
                    Uuid4(),
                    181,
                    187,
                )
                accepted = OrderAccepted(
                    self.trader_id,
                    command.strategy_id,
                    command.instrument_id,
                    command.client_order_id,
                    VenueOrderId("CANCEL-181"),
                    self.account_id,
                    Uuid4(),
                    191,
                    192,
                    False,
                )

                if output == "event":
                    self._handle_event(submitted)
                    self._handle_event(accepted)
                else:
                    self._handle_order_submitted_batch([submitted])
                    self._handle_order_accepted_batch([accepted])

        async def _cancel_all_orders(self, command):
            commands.append(command)
            for order in self.cache.orders_open(
                instrument_id=command.instrument_id,
                side=command.order_side,
            ):
                if output == "generated":
                    self.generate_order_canceled(order, order.venue_order_id, 193)
                else:
                    canceled = OrderCanceled(
                        self.trader_id,
                        order.strategy_id,
                        order.instrument_id,
                        order.client_order_id,
                        Uuid4(),
                        193,
                        197,
                        False,
                        order.venue_order_id,
                        self.account_id,
                        "Venue cancellation",
                    )

                    if output == "event":
                        self._handle_event(canceled)
                    else:
                        self._handle_order_canceled_batch([canceled])

    class Consumer(Strategy):
        def on_start(self):
            self.order = self.order_factory.limit(
                CONTRACT_ID,
                OrderSide.BUY,
                Quantity.from_str("17"),
                Price.from_str("1905.8"),
                time_in_force=TimeInForce.DAY,
            )
            self.submit_order(self.order)

        def on_order_accepted(self, event):  # noqa: ARG002 - Preserve the strategy callback signature.
            self.cancel_all_orders(
                CONTRACT_ID,
                order_side=OrderSide.BUY,
                client_id=ClientId("DNSE"),
                strategy_only=False,
                params=params,
            )

        def on_order_canceled(self, event):
            received.append(event)
            self.shutdown_system("Cancel all completed")

    node, consumer = build_node(exec_factory=make_exec_factory(Client), strategy=Consumer())
    asyncio.run(run_hosted(node))

    assert len(commands) == 1
    command = commands[0]
    assert command.trader_id == TraderId("TRADER-001")
    assert command.strategy_id == consumer.strategy_id
    assert command.client_id == ClientId("DNSE")
    assert command.instrument_id == CONTRACT_ID
    assert command.order_side == OrderSide.BUY
    assert command.params == params
    assert len(received) == 1
    assert received[0].client_order_id == consumer.order.client_order_id
    assert received[0].venue_order_id == VenueOrderId("CANCEL-181")
    assert received[0].ts_event == 193
    assert node.cache.order(received[0].client_order_id).status == OrderStatus.CANCELED

    if output != "generated":
        assert received[0].ts_init == 197
        assert received[0].reason == "Venue cancellation"
        assert received[0].account_id == AccountId("DNSE-456")
        assert received[0].trader_id == TraderId("TRADER-001")
        assert received[0].strategy_id == consumer.strategy_id
        assert received[0].instrument_id == CONTRACT_ID
        assert received[0].reconciliation is False
