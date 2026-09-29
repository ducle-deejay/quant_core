"""End-to-end runs of the Entrade/DNSE adapter inside a real Nautilus LiveNode.

The Nautilus engines (data, risk, execution, portfolio) are real; only the DNSE and
Entrade network services are replaced by fakes. These runs prove that orders built the
way strategies build them reach the broker as the intended HNX order and come back as
fills and positions.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from dnse.websocket.models import Ohlc
from dnse.websocket.models import Quote

from nautilus_trader.common import Environment
from nautilus_trader.config import LiveNodeConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.live.clients import DataClientFactory, ExecutionClientFactory
from nautilus_trader.model import (
    AccountId,
    InstrumentId,
    OrderSide,
    OrderStatus,
    Price,
    Quantity,
    TimeInForce,
    TraderId,
)
from nautilus_trader.trading import Strategy

from nautilus_bridge.adapters.entrade.config import DnseDataClientConfig
from nautilus_bridge.adapters.entrade.config import EntradeExecClientConfig
from nautilus_bridge.adapters.entrade.data import DnseLiveDataClient
from nautilus_bridge.adapters.entrade.data import build_bar_type_for_symbol
from nautilus_bridge.adapters.entrade.execution import EntradeExecutionClient
from nautilus_bridge.adapters.entrade.providers import DnseInstrumentProvider
from nautilus_bridge.adapters.entrade.providers import EntradeInstrumentProvider
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1MResolver

VENUE = "HNX"
DATA_SYMBOL = "VN30F1M"
CONTRACT_SYMBOL = "41I1G8000"
CONTRACT_ID = InstrumentId.from_str(f"{CONTRACT_SYMBOL}.{VENUE}")
# The test strategy trades the continuous symbol.
TRADED_ID = InstrumentId.from_str(f"{DATA_SYMBOL}.{VENUE}")
# 2025-01-02 02:00 UTC, a Thursday so the weekday gate lets the bar through.
BAR_TIME_SECONDS = 1_735_783_200


class FakeDnseTradingClient:
    """Delivers one closed bar as soon as bars are subscribed."""

    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}

    def on(self, event: str, handler: object) -> None:
        self.handlers.setdefault(event, []).append(handler)

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def subscribe_ohlc_closed(self, **kwargs: object) -> None:
        ohlc = Ohlc.from_dict(
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
                "type": "ohlc",
            },
        )
        for handler in self.handlers.get("ohlc_closed", []):
            handler(ohlc)


    async def subscribe_quotes(self, symbols: list[str], **kwargs: object) -> None:
        for symbol in symbols:
            quote = Quote.from_dict(
                {
                    "symbol": symbol,
                    "boardId": "G1",
                    "bid": [{"price": 1905.7, "qtty": 5}],
                    "offer": [{"price": 1905.8, "qtty": 7}],
                },
            )
            for handler in self.handlers.get("quote", []):
                handler(quote)


class FakeDnseRestClient:
    def get_ohlc(self, **kwargs: object) -> tuple[int, dict]:
        return 200, {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}


class FakeEntradeClient:
    """Fills every order in full at 1905.8 and records what the adapter sent."""

    def __init__(self) -> None:
        self.order_requests: list[dict] = []
        self.orders: dict[int, dict] = {}

    def authenticate(self, username: str, password: str) -> str:
        return "test-token"

    def get_account_balance(self, investor_id: int | str) -> dict:
        return {"investorAccountId": 456, "nav": 100_000_000, "availableCash": 90_000_000}

    def list_margin_portfolios(self, investor_id: int | str) -> dict:
        return {"data": [{"id": 32}]}

    def list_derivatives(self) -> dict:
        return {
            "data": [
                {
                    "symbol": CONTRACT_SYMBOL,
                    "type": "VN30F2M",
                    "expirationDate": "2027-08-20T00:00:00.000Z",
                    "marketPrice": 1535.2,
                },
            ],
        }

    def get_buying_power(self, **kwargs: object) -> dict:
        return {"qmax": 10}

    def place_order(self, **kwargs: object) -> dict:
        self.order_requests.append(kwargs)
        order_id = 7001 + len(self.orders)
        quantity = int(kwargs["quantity"])
        self.orders[order_id] = {
            "id": order_id,
            "symbol": kwargs["symbol"],
            "side": kwargs["side"],
            "price": kwargs["price"],
            "quantity": quantity,
            "orderType": kwargs["order_type"],
            "orderStatus": "Filled",
            "fillQuantity": quantity,
            "averagePrice": 1905.8,
            "tradingFee": 15_750 * quantity,
            "tradingTax": 0.0,
            "reports": [
                {
                    "version": 1,
                    "execType": "F",
                    "lastQuantity": quantity,
                    "lastPrice": 1905.8,
                    "modifiedDate": "2026-09-15T02:21:48.100Z",
                },
            ],
        }
        return self.orders[order_id]

    def get_order(self, order_id: int | str) -> dict:
        return self.orders[int(order_id)]

    def list_all_orders(self, **kwargs: object) -> list[dict]:
        return list(self.orders.values())

    def list_all_deals(self, **kwargs: object) -> list[dict]:
        return []

    def close(self) -> None:
        return None


class OneOrderStrategy(Strategy):
    """Submit one buy on the first bar, the way a strategy normally builds it."""

    def __init__(self, order_kind: str) -> None:
        super().__init__()
        self.order_kind = order_kind
        self.bar: Any = None
        self.order: Any = None
        self.fill: Any = None

    def on_start(self) -> None:
        # Bars only: the risk engine prices a MARKET order from the latest bar of the
        # traded instrument when no quote is cached.
        self.subscribe_bars(build_bar_type_for_symbol(DATA_SYMBOL, "1", VENUE))

    def on_bar(self, bar) -> None:
        if self.bar is not None:
            return
        self.bar = bar
        if self.order_kind == "market":
            # No time in force given: Nautilus defaults to GTC.
            self.order = self.order_factory.market(TRADED_ID, OrderSide.BUY, Quantity.from_int(1))
        else:
            self.order = self.order_factory.limit(
                TRADED_ID,
                OrderSide.BUY,
                Quantity.from_int(1),
                price=Price.from_str("1905.8"),
                time_in_force=TimeInForce.GTD,
                expire_time=self.clock.timestamp_ns() + 180_000_000_000,
            )
        self.submit_order(self.order)

    def on_order_denied(self, event) -> None:
        self.shutdown_system(f"Order denied: {event.reason}")

    def on_order_rejected(self, event) -> None:
        self.shutdown_system(f"Order rejected: {event.reason}")

    def on_order_filled(self, event) -> None:
        self.fill = event
        self.shutdown_system("Order filled")


def build_node(tmp_path: Path, strategy: Strategy) -> tuple[LiveNode, FakeEntradeClient]:
    trading = FakeDnseTradingClient()
    rest = FakeDnseRestClient()
    api = FakeEntradeClient()

    class DataFactory(DataClientFactory):
        @staticmethod
        def create(*, name: str, config, cache, clock):
            return DnseLiveDataClient(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                venue=config.venue,
                instrument_provider=DnseInstrumentProvider(config, clock),
                trading_client=trading,
                rest_client=rest,
            )

    class ExecFactory(ExecutionClientFactory):
        @staticmethod
        def create(*, name: str, config, cache, clock, trader_id):
            provider = EntradeInstrumentProvider(api, config.instrument_provider, clock=clock)
            return EntradeExecutionClient(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                trader_id=trader_id,
                instrument_provider=provider,
                client=api,
                symbol_resolver=VN30F1MResolver(provider.list_all),
            )

    node = LiveNode.build(
        "ENTRADE-TEST",
        LiveNodeConfig(
            environment=Environment.SANDBOX,
            trader_id=TraderId("TRADER-001"),
            timeout_connection_secs=2,
            timeout_reconciliation_secs=2,
            timeout_portfolio_secs=2,
            timeout_disconnection_secs=3,
            delay_post_stop_secs=0,
            data_clients={
                "DNSE": DnseDataClientConfig(
                    api_key="key",
                    api_secret="secret",
                    historical_source="api",
                ),
            },
            exec_clients={
                "DNSE": EntradeExecClientConfig(
                    username="user",
                    password="password",
                    investor_id=123,
                    account_id="DNSE-456",
                ),
            },
        ),
        data_factories={"DNSE": DataFactory},
        exec_factories={"DNSE": ExecFactory},
    )
    node.add_strategy(strategy)
    return node, api


async def run_hosted(node: LiveNode) -> None:
    async with asyncio.timeout(15):
        await node.run_async()


@pytest.mark.parametrize(
    ("order_kind", "expected_wire_type"),
    [("market", "MTL"), ("limit_gtd", "LO")],
)
def test_strategy_order_reaches_entrade_as_the_hnx_order_and_fills(
    tmp_path: Path,
    order_kind: str,
    expected_wire_type: str,
) -> None:
    strategy = OneOrderStrategy(order_kind)
    node, api = build_node(tmp_path, strategy)

    asyncio.run(run_hosted(node))

    assert [
        (request["symbol"], request["order_type"]) for request in api.order_requests
    ] == [(CONTRACT_SYMBOL, expected_wire_type)]
    assert strategy.fill is not None, "the order never filled"
    assert strategy.fill.account_id == AccountId("DNSE-456")
    assert strategy.fill.instrument_id == TRADED_ID
    assert strategy.fill.last_qty == Quantity.from_int(1)
    assert strategy.fill.last_px == Price.from_str("1905.8")
    assert node.cache.order(strategy.order.client_order_id).status == OrderStatus.FILLED
    position = node.cache.positions_open(instrument_id=TRADED_ID)
    assert [p.quantity for p in position] == [Quantity.from_int(1)]


def test_adapter_runs_on_the_node_owned_event_loop(tmp_path: Path) -> None:
    strategy = OneOrderStrategy("limit_gtd")
    node, api = build_node(tmp_path, strategy)

    node.run()

    assert len(api.order_requests) == 1
    assert strategy.fill is not None
