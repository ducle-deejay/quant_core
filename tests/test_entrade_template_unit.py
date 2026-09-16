from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from dnse.websocket.models import Ohlc
from dnse.websocket.models import Quote
from dnse.websocket.models import Trade
from nautilus_trader.core import UUID4
from nautilus_trader.live import BarsResponse, InstrumentResponse, InstrumentsResponse
from nautilus_trader.model import (
    AccountBalance,
    AggressorSide,
    AccountId,
    Bar,
    ClientOrderId,
    InstrumentId,
    MarketOrder,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    Price,
    Quantity,
    StrategyId,
    TimeInForce,
    TradeId,
    TraderId,
    VenueOrderId,
)

from trading.adapters.entrade_template.config import DnseDataClientConfig
from trading.adapters.entrade_template.config import EntradeExecClientConfig
from trading.adapters.entrade_template.data import (
    DnseLiveDataClient,
    SubscriptionKey,
    bar_type_to_dnse_resolution,
    build_bar_type_for_symbol,
    dnse_ohlc_body_to_nautilus_bars,
    dnse_quote_to_nautilus_depth10,
    dnse_quote_to_nautilus_quote_tick,
    dnse_trade_to_nautilus_trade_tick,
    normalize_dnse_resolution,
)
from trading.adapters.entrade_template.execution import (
    EntradeExecutionClient,
    EntradeOrderContext,
    entrade_account_balance,
    entrade_order_parameters,
    entrade_order_status,
    entrade_order_type,
)
from trading.adapters.entrade_template.api.entrade_api import EntradeAccount
from trading.adapters.entrade_template.api.entrade_api import EntradeClient
from trading.adapters.entrade_template.api.entrade_api import EntradeClientConfig
from trading.adapters.entrade_template.providers import DnseInstrumentProvider
from trading.adapters.entrade_template.providers import EntradeInstrumentProvider
from trading.instruments import FuturesInstrumentSpec

SPEC = FuturesInstrumentSpec(
    symbol="VN30F1M",
    venue="HNX",
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


class FakeClock:
    def timestamp_ns(self) -> int:
        return 1_800_000_000_000_000_000


class FakeDnseTradingClient:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.connected = False
        self.subscriptions: list[dict] = []
        self.quote_subscriptions: list[dict] = []
        self.trade_subscriptions: list[dict] = []
        self.unsubscribes: list[tuple[str, list[str]]] = []

    def on(self, event: str, handler: object) -> None:
        self.handlers[event] = handler

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def subscribe_ohlc_closed(self, **kwargs: object) -> None:
        self.subscriptions.append(kwargs)

    async def subscribe_quotes(self, **kwargs: object) -> None:
        self.quote_subscriptions.append(kwargs)

    async def subscribe_trades(self, **kwargs: object) -> None:
        self.trade_subscriptions.append(kwargs)

    async def unsubscribe(self, channel: str, symbols: list[str]) -> None:
        self.unsubscribes.append((channel, symbols))


class FakeDnseRestClient:
    def __init__(self, status: int = 200, body: dict | None = None) -> None:
        self.status = status
        self.body = body
        self.ohlc_calls: list[dict] = []

    def get_ohlc(self, **kwargs: object) -> tuple[int, dict]:
        self.ohlc_calls.append(kwargs)
        return self.status, self.body or {
            "t": [1735783200, 1735869600],
            "o": [1000.0, 990.0],
            "h": [1001.0, 991.0],
            "l": [999.0, 989.0],
            "c": [1000.5, 990.5],
            "v": [10, 5],
        }

    def get_working_dates(self, **kwargs: object) -> tuple[int, dict]:
        return 200, {"workingDates": ["2025-01-02"]}


class RecordingDnseClient(DnseLiveDataClient):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.responses: list[object] = []
        self.instruments: list[object] = []
        self.data: list[object] = []

    def _handle_response(self, response: object) -> None:
        self.responses.append(response)

    def _handle_instrument(self, instrument: object) -> None:
        self.instruments.append(instrument)

    def _handle_data(self, data: object) -> None:
        self.data.append(data)


def _dnse_client(
    *,
    historical_source: str = "api",
    rest: FakeDnseRestClient | None = None,
) -> tuple[RecordingDnseClient, FakeDnseTradingClient, FakeDnseRestClient]:
    config = DnseDataClientConfig(
        api_key="key",
        api_secret="secret",
        instrument_spec=SPEC,
        symbols=("VN30F1M",),
        historical_source=historical_source,
        market_working_dates=("2025-01-02",),
    )
    trading = FakeDnseTradingClient()
    rest = rest or FakeDnseRestClient()
    client = RecordingDnseClient(
        name="DNSE",
        config=config,
        cache=None,
        clock=FakeClock(),
        venue="HNX",
        instrument_provider=DnseInstrumentProvider(config),
        trading_client=trading,
        rest_client=rest,
    )
    return client, trading, rest


def test_dnse_connect_binds_resources_and_publishes_instrument() -> None:
    client, trading, _ = _dnse_client()
    assert client.loop is None

    asyncio.run(client._connect())

    assert trading.connected
    assert set(trading.handlers) == {"ohlc_closed", "reconnected"}
    assert len(client.instruments) == 1


def test_dnse_resolution_and_ohlc_conversion_preserve_domain_values() -> None:
    assert normalize_dnse_resolution("60") == "1H"
    bar_type = build_bar_type_for_symbol("VN30F1M", "1", "HNX")
    assert bar_type_to_dnse_resolution(bar_type) == "1"

    bars = dnse_ohlc_body_to_nautilus_bars(
        {
            "t": [1735783200],
            "o": [1000.0],
            "h": [1001.0],
            "l": [999.0],
            "c": [1000.5],
            "v": [10],
        },
        symbol="VN30F1M",
        resolution="1",
        venue="HNX",
        working_dates=("2025-01-02",),
    )

    assert len(bars) == 1
    assert bars[0].bar_type == bar_type
    assert bars[0].open.as_decimal() == 1000
    assert bars[0].close.as_decimal() == 1000.5


def test_dnse_closed_bars_filter_working_days_and_duplicates() -> None:
    client, _, _ = _dnse_client()
    bar_type = build_bar_type_for_symbol("VN30F1M", "1", "HNX")
    client._bar_types_by_key[SubscriptionKey("VN30F1M", "1")] = bar_type

    for timestamp, close in (
        (1735869600, 990.5),  # filtered working-day exclusion
        (1735783200, 1000.5),
        (1735783200, 1001.5),  # duplicate timestamp
        (1735783260, 1002.5),
    ):
        client._on_ohlc_event(
            Ohlc.from_dict(
                {
                    "symbol": "VN30F1M",
                    "resolution": "1",
                    "open": close - 1,
                    "high": close + 1,
                    "low": close - 2,
                    "close": close,
                    "volume": 10,
                    "time": timestamp,
                    "lastUpdated": timestamp,
                    "type": "ohlc",
                },
            ),
        )

    published = [data for data in client.data if isinstance(data, Bar)]
    assert [bar.close.as_decimal() for bar in published] == [1000.5, 1002.5]


def test_dnse_instrument_requests_and_api_failure_use_typed_path() -> None:
    client, _, _ = _dnse_client()
    instrument_id = build_bar_type_for_symbol("VN30F1M", "1", "HNX").instrument_id
    asyncio.run(
        client._request_instrument(
            SimpleNamespace(
                request_id=UUID4(),
                instrument_id=instrument_id,
                start=None,
                end=None,
                start_ns=None,
                end_ns=None,
                params={},
            ),
        ),
    )
    assert isinstance(client.responses[-1], InstrumentResponse)
    assert client.responses[-1].instrument_id == instrument_id

    asyncio.run(
        client._request_instruments(
            SimpleNamespace(
                request_id=UUID4(),
                venue=instrument_id.venue,
                start=None,
                end=None,
                start_ns=None,
                end_ns=None,
                params={},
            ),
        ),
    )
    assert isinstance(client.responses[-1], InstrumentsResponse)

    failing_rest = FakeDnseRestClient(status=503, body={"error": "unavailable"})
    failing, _, _ = _dnse_client(rest=failing_rest)
    failing_request = SimpleNamespace(
        request_id=UUID4(),
        bar_type=build_bar_type_for_symbol("VN30F1M", "1", "HNX"),
        start=datetime(2025, 1, 2, 2, tzinfo=UTC),
        end=datetime(2025, 1, 3, 2, tzinfo=UTC),
        start_ns=1735783200000000000,
        end_ns=1735869600000000000,
        params={},
    )
    try:
        asyncio.run(failing._request_bars(failing_request))
    except ValueError as error:
        assert "DNSE get_ohlc failed" in str(error)
    else:
        raise AssertionError("DNSE API failure did not propagate")


def test_dnse_catalog_source_falls_back_to_api_when_catalog_has_no_rows() -> None:
    client, _, rest = _dnse_client(historical_source="catalog")
    request = SimpleNamespace(
        request_id=UUID4(),
        bar_type=build_bar_type_for_symbol("VN30F1M", "1", "HNX"),
        start=datetime(2025, 1, 2, 2, tzinfo=UTC),
        end=datetime(2025, 1, 3, 2, tzinfo=UTC),
        start_ns=1735783200000000000,
        end_ns=1735869600000000000,
        params={},
    )

    asyncio.run(client._request_bars(request))

    assert len(rest.ohlc_calls) == 1
    assert isinstance(client.responses[-1], BarsResponse)


def test_dnse_historical_request_emits_typed_rc5_response() -> None:
    client, _, _ = _dnse_client()
    bar_type = build_bar_type_for_symbol("VN30F1M", "1", "HNX")
    request = SimpleNamespace(
        request_id=UUID4(),
        bar_type=bar_type,
        start=datetime(2025, 1, 2, 2, tzinfo=UTC),
        end=datetime(2025, 1, 3, 2, tzinfo=UTC),
        start_ns=1735783200000000000,
        end_ns=1735869600000000000,
        params={"test": True},
    )

    asyncio.run(client._request_bars(request))

    assert len(client.responses) == 1
    response = client.responses[0]
    assert isinstance(response, BarsResponse)
    assert response.correlation_id == request.request_id
    assert len(response.data) == 1
    assert response.data[0].bar_type == bar_type


def test_dnse_reconnect_buffers_live_bar_until_history_request_completes() -> None:
    client, trading, _ = _dnse_client()
    bar_type = build_bar_type_for_symbol("VN30F1M", "1", "HNX")
    asyncio.run(client._subscribe_bars(SimpleNamespace(bar_type=bar_type)))
    client._on_reconnected({"session_id": "next"})

    client._on_ohlc_event(
        Ohlc.from_dict(
            {
                "symbol": "VN30F1M",
                "resolution": "1",
                "open": 1000.0,
                "high": 1001.0,
                "low": 999.0,
                "close": 1000.5,
                "volume": 10,
                "time": 1735783260,
                "lastUpdated": 1735783260,
                "type": "ohlc",
            },
        ),
    )

    assert len(trading.subscriptions) == 1
    assert client.data == []  # rc5 output accepts only typed market-data objects
    assert len(next(iter(client._buffered_ohlc_by_key.values()))) == 1

    request = SimpleNamespace(
        request_id=UUID4(),
        bar_type=bar_type,
        start=datetime(2025, 1, 2, 2, tzinfo=UTC),
        end=datetime(2025, 1, 3, 2, tzinfo=UTC),
        start_ns=1735783200000000000,
        end_ns=1735869600000000000,
        params={},
    )
    asyncio.run(client._request_bars(request))

    assert not client._recovering_keys
    assert len(client.data) == 1


class FakeEntradeClient:
    def __init__(self) -> None:
        self.order_requests: list[dict] = []
        self.closed = False
        self.qmax = 2
        self.orders: list[dict] = []
        self.deals: list[dict] = []
        self.cancel_calls: list[int | str] = []
        self.get_order_calls: list[int | str] = []

    def authenticate(self, username: str, password: str) -> str:
        claims = base64.urlsafe_b64encode(
            json.dumps({"investorId": 123}).encode()
        ).decode()
        return f"header.{claims.rstrip('=')}.signature"

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
        return {"qmax": self.qmax}

    def place_order(self, **kwargs: object) -> dict:
        self.order_requests.append(kwargs)
        quantity = kwargs["quantity"]
        payload = {
            "id": 7001,
            "symbol": "41I1G8000",
            "side": "NB",
            "price": 0.0,
            "quantity": quantity,
            "orderType": "MAK",
            "orderStatus": "Filled",
            "fillQuantity": quantity,
            "averagePrice": 1905.8,
            "tradingFee": 31_500.0,
            "tradingTax": 0.0,
            "reports": [
                {
                    "version": 1,
                    "execType": "F",
                    "lastQuantity": quantity,
                    "lastPrice": 1905.8,
                    "modifiedDate": "2026-07-20T04:21:48.100Z",
                },
            ],
        }
        self.orders.append(payload)
        return payload

    def get_order(self, order_id: int | str) -> dict:
        self.get_order_calls.append(order_id)
        return self.orders[-1] if self.orders else self.place_order(quantity=2)

    def cancel_order(self, order_id: int | str) -> dict:
        self.cancel_calls.append(order_id)
        return {
            "id": order_id,
            "symbol": "41I1G8000",
            "side": "NB",
            "quantity": 2,
            "orderType": "MAK",
            "orderStatus": "Canceled",
            "fillQuantity": 0,
            "averagePrice": 0,
            "reports": [],
        }

    def list_orders(self, **kwargs: object) -> dict:
        return {"data": self.orders}

    def list_deals(self, **kwargs: object) -> dict:
        return {"data": self.deals}

    def close(self) -> None:
        self.closed = True


class RecordingEntradeClient(EntradeExecutionClient):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.events: list[tuple[str, tuple]] = []

    def _generate_balance(self, payload: dict) -> None:
        return None

    def _handle_instrument(self, instrument: object) -> None:
        return None

    def generate_order_submitted(self, *args: object) -> None:
        self.events.append(("submitted", args))

    def generate_order_accepted(self, *args: object) -> None:
        self.events.append(("accepted", args))

    def generate_order_updated(self, *args: object) -> None:
        self.events.append(("updated", args))

    def generate_order_filled(self, *args: object) -> None:
        self.events.append(("filled", args))

    def generate_order_rejected(self, *args: object) -> None:
        self.events.append(("rejected", args))

    def generate_order_canceled(self, *args: object) -> None:
        self.events.append(("canceled", args))

    def generate_order_expired(self, *args: object) -> None:
        self.events.append(("expired", args))

    def generate_order_modify_rejected(self, *args: object) -> None:
        self.events.append(("modify_rejected", args))

    def generate_order_cancel_rejected(self, *args: object) -> None:
        self.events.append(("cancel_rejected", args))


def _entrade_client(
    account_id: str = "ENTRADE-456",
) -> tuple[RecordingEntradeClient, FakeEntradeClient, EntradeInstrumentProvider]:
    api = FakeEntradeClient()
    config = EntradeExecClientConfig(
        instrument_spec=SPEC,
        username="user",
        password="password",
        account_id=account_id,
        account=EntradeAccount.DEMO,
    )
    provider = EntradeInstrumentProvider(api, SPEC)
    client = RecordingEntradeClient(
        name="ENTRADE",
        config=config,
        cache=None,
        clock=FakeClock(),
        trader_id=TraderId("TRADER-001"),
        instrument_provider=provider,
        client=api,
    )
    return client, api, provider


@pytest.mark.parametrize(
    ("account", "margin_portfolio_parameter"),
    [
        (EntradeAccount.DEMO, "bankMarginPortfolioId"),
        (EntradeAccount.LIVE, "bankMarginPortfolio"),
    ],
)
def test_entrade_buying_power_uses_account_specific_margin_parameter(
    account: EntradeAccount,
    margin_portfolio_parameter: str,
) -> None:
    client = EntradeClient(EntradeClientConfig(account=account))

    with patch.object(client, "_request", return_value={}) as request:
        client.get_buying_power(
            investor_id=123,
            margin_portfolio_id=32,
            symbol="41I1G8000",
            side="NB",
            price=1535.2,
        )

    assert request.call_args.kwargs["params"] == {
        margin_portfolio_parameter: 32,
        "price": 1535.2,
        "symbol": "41I1G8000",
        "side": "NB",
    }


def test_entrade_connect_rejects_an_authenticated_account_mismatch() -> None:
    client, _, _ = _entrade_client(account_id="ENTRADE-999")

    try:
        asyncio.run(client._connect())
    except ValueError as e:
        assert "does not match the authenticated account" in str(e)
    else:
        raise AssertionError("Entrade accepted a mismatched account identity")


def test_entrade_connect_and_submit_preserves_qmax_and_fill_flow() -> None:
    client, api, provider = _entrade_client()

    async def run() -> None:
        await client._connect()
        instrument = provider.resolve_active_instrument()
        order = MarketOrder(
            TraderId("TRADER-001"),
            StrategyId("S-001"),
            instrument.id,
            ClientOrderId("O-001"),
            OrderSide.BUY,
            instrument.make_qty(5),
            UUID4(),
            1,
            TimeInForce.IOC,
            False,
            False,
        )
        await client._submit_order(SimpleNamespace(order=order))

    asyncio.run(run())

    assert client.account_id == AccountId("ENTRADE-456")
    assert client._investor_account_id == 456
    assert api.order_requests[0]["quantity"] == 2
    assert [name for name, _ in client.events] == [
        "submitted",
        "accepted",
        "updated",
        "filled",
    ]


def test_entrade_order_type_and_status_mappings_cover_supported_wire_values() -> None:
    client, _, provider = _entrade_client()
    asyncio.run(client._connect())
    instrument = provider.resolve_active_instrument()

    limit = type(
        "LimitLikeOrder",
        (),
        {
            "side": OrderSide.BUY,
            "quantity": instrument.make_qty(2),
            "order_type": OrderType.LIMIT,
            "time_in_force": TimeInForce.DAY,
            "price": instrument.make_price(1900.5),
        },
    )()
    assert entrade_order_parameters(limit) == ("NB", "LO", 2, 1900.5)
    assert entrade_order_status("PartiallyFilled") == OrderStatus.PARTIALLY_FILLED
    assert entrade_order_status("DoneForDay") == OrderStatus.EXPIRED
    assert entrade_order_type("MAK")[0].name == "MARKET"


@pytest.mark.parametrize(
    ("order_type", "time_in_force", "side", "order_price", "expected"),
    [
        (
            OrderType.LIMIT,
            TimeInForce.DAY,
            OrderSide.SELL,
            1900.5,
            ("NS", "LO", 2, 1900.5),
        ),
        (
            OrderType.MARKET_TO_LIMIT,
            TimeInForce.DAY,
            OrderSide.SELL,
            0.0,
            ("NS", "MTL", 2, 0.0),
        ),
        (
            OrderType.MARKET,
            TimeInForce.IOC,
            OrderSide.BUY,
            0.0,
            ("NB", "MAK", 2, 0.0),
        ),
        (
            OrderType.MARKET,
            TimeInForce.FOK,
            OrderSide.SELL,
            0.0,
            ("NS", "MOK", 2, 0.0),
        ),
    ],
)
def test_entrade_order_parameters_cover_supported_order_combinations(
    order_type: OrderType,
    time_in_force: TimeInForce,
    side: OrderSide,
    order_price: float,
    expected: tuple[str, str, int, float],
) -> None:
    order = SimpleNamespace(
        side=side,
        quantity=Quantity.from_int(2),
        order_type=order_type,
        time_in_force=time_in_force,
        price=Price.from_str(str(order_price)),
    )

    assert entrade_order_parameters(order) == expected


def test_entrade_rejects_limit_gtc_without_downgrading_to_day_order() -> None:
    order = SimpleNamespace(
        side=OrderSide.BUY,
        quantity=Quantity.from_int(1),
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price=Price.from_str("1900.5"),
    )

    with pytest.raises(ValueError, match="LIMIT with GTC is unsupported"):
        entrade_order_parameters(order)


def test_entrade_rejects_unsupported_orders_and_zero_qmax_without_broker_order() -> (
    None
):
    client, api, provider = _entrade_client()
    asyncio.run(client._connect())
    instrument = provider.resolve_active_instrument()
    order = MarketOrder(
        TraderId("TRADER-001"),
        StrategyId("S-001"),
        instrument.id,
        ClientOrderId("O-002"),
        OrderSide.BUY,
        instrument.make_qty(1),
        UUID4(),
        1,
        TimeInForce.GTC,
        False,
        False,
    )
    asyncio.run(client._submit_order(SimpleNamespace(order=order)))
    assert api.order_requests == []
    assert client.events[-1][0] == "rejected"
    assert "Unsupported Entrade order combination" in client.events[-1][1][1]

    api.qmax = 0
    order = MarketOrder(
        TraderId("TRADER-001"),
        StrategyId("S-001"),
        instrument.id,
        ClientOrderId("O-003"),
        OrderSide.BUY,
        instrument.make_qty(1),
        UUID4(),
        1,
        TimeInForce.IOC,
        False,
        False,
    )
    asyncio.run(client._submit_order(SimpleNamespace(order=order)))
    assert len(api.order_requests) == 0
    assert "qmax is zero" in client.events[-1][1][1]


def test_entrade_fill_deduplication_and_cancel_reconciliation() -> None:
    client, _, provider = _entrade_client()
    asyncio.run(client._connect())
    instrument = provider.resolve_active_instrument()
    order = MarketOrder(
        TraderId("TRADER-001"),
        StrategyId("S-001"),
        instrument.id,
        ClientOrderId("O-004"),
        OrderSide.BUY,
        instrument.make_qty(2),
        UUID4(),
        1,
        TimeInForce.IOC,
        False,
        False,
    )
    context = EntradeOrderContext(order, VenueOrderId("7002"), set())
    partial = {
        "id": 7002,
        "symbol": "41I1G8000",
        "side": "NB",
        "quantity": 2,
        "orderType": "MAK",
        "orderStatus": "PartiallyFilled",
        "fillQuantity": 1,
        "averagePrice": 1905.8,
        "tradingFee": 15_750,
        "tradingTax": 0,
        "modifiedDate": "2026-07-20T04:21:48.104Z",
        "reports": [
            {
                "version": 1,
                "execType": "F",
                "lastQuantity": 1,
                "lastPrice": 1905.8,
                "modifiedDate": "2026-07-20T04:21:48.100Z",
            },
        ],
    }
    client._synchronize_order(partial, context)
    client._synchronize_order(partial, context)
    client._synchronize_order({**partial, "orderStatus": "Canceled"}, context)

    assert [name for name, _ in client.events] == ["filled", "canceled"]


def test_entrade_cancel_endpoint_and_poll_stop_on_terminal_status() -> None:
    client, api, provider = _entrade_client()
    asyncio.run(client._connect())
    instrument = provider.resolve_active_instrument()
    order = MarketOrder(
        TraderId("TRADER-001"),
        StrategyId("S-001"),
        instrument.id,
        ClientOrderId("O-005"),
        OrderSide.BUY,
        instrument.make_qty(2),
        UUID4(),
        1,
        TimeInForce.IOC,
        False,
        False,
    )
    context = EntradeOrderContext(order, VenueOrderId("7003"), set())
    client._orders[order.client_order_id] = context
    cancel_command = SimpleNamespace(
        client_order_id=order.client_order_id,
        venue_order_id=VenueOrderId("7003"),
    )
    asyncio.run(client._cancel_order(cancel_command))
    assert api.cancel_calls == ["7003"]
    assert client.events[-1][0] == "canceled"

    terminal = api.place_order(quantity=2)
    terminal["id"] = 7004
    api.orders[-1] = terminal
    poll_context = EntradeOrderContext(order, VenueOrderId("7004"), set())
    with patch("trading.adapters.entrade_template.execution.asyncio.sleep", new=_no_sleep):
        asyncio.run(client._poll_order(poll_context))
    assert api.get_order_calls[-1] == "7004"


async def _no_sleep(seconds: float) -> None:
    return None


def test_entrade_account_order_fill_position_and_mass_reports_are_exact() -> None:
    client, api, provider = _entrade_client()
    asyncio.run(client._connect())
    instrument = provider.resolve_active_instrument()
    payload = api.place_order(quantity=2)
    api.deals = [
        {
            "id": 8001,
            "symbol": instrument.id.symbol.value,
            "side": "NB",
            "openQuantity": 3,
            "positionCostPrice": "1903.333333333333333333",
            "status": "ACTIVE",
            "modifiedDate": "2026-07-20T04:21:48.100Z",
        },
    ]

    balance = entrade_account_balance(
        {"nav": "100000000.00", "availableCash": "90000000.00"},
        SPEC.quote_currency(),
    )
    status_report = client._order_status_report(payload)
    fill_reports = client._fill_reports(payload)
    position_reports = client._position_status_reports(api.deals)
    mass_status = asyncio.run(client._generate_mass_status())

    assert isinstance(balance, AccountBalance)
    assert balance.locked.as_decimal() == 10_000_000
    assert status_report.order_status == OrderStatus.FILLED
    assert status_report.avg_px == Decimal("1905.8")
    assert fill_reports[0].commission.as_decimal() == 31_500
    assert position_reports[0].position_side == PositionSide.LONG
    assert position_reports[0].avg_px_open == Decimal("1903.333333333333333333")
    assert mass_status is not None
    assert len(mass_status.order_reports) == 1
    assert len(mass_status.fill_reports[VenueOrderId("7001")]) == 1
    assert len(mass_status.position_reports) == 1


def test_dnse_quote_conversion_preserves_top_of_book() -> None:
    quote = Quote.from_dict(
        {
            "symbol": "VN30F1M",
            "bid": [{"price": 1000.0, "qtty": 5}],
            "offer": [{"price": 1000.5, "qtty": 7}],
            "receivedAt": 1735783200.0,
        },
    )
    tick = dnse_quote_to_nautilus_quote_tick(quote, venue="HNX")
    assert tick.instrument_id == InstrumentId.from_str("VN30F1M.HNX")
    assert tick.bid_price == Price.from_str("1000.0")
    assert tick.ask_price == Price.from_str("1000.5")
    assert tick.bid_size == Quantity.from_int(5)
    assert tick.ask_size == Quantity.from_int(7)


def test_dnse_quote_missing_ask_raises() -> None:
    quote = Quote.from_dict(
        {"symbol": "VN30F1M", "bid": [{"price": 1000.0, "qtty": 5}]},
    )
    with pytest.raises(ValueError):
        dnse_quote_to_nautilus_quote_tick(quote, venue="HNX")


def test_dnse_subscribe_quotes_routes_sdk_events() -> None:
    client, trading, _ = _dnse_client()
    command = SimpleNamespace(
        instrument_id=build_bar_type_for_symbol("VN30F1M", "1", "HNX").instrument_id,
    )
    asyncio.run(client._subscribe_quotes(command))
    assert len(trading.quote_subscriptions) == 1
    subscription = trading.quote_subscriptions[0]
    assert subscription["symbols"] == ["VN30F1M"]
    assert subscription["encoding"] == "json"

    asyncio.run(client._subscribe_quotes(command))
    assert len(trading.quote_subscriptions) == 1  # duplicate subscribe is deduped

    subscription["on_quote"](
        Quote.from_dict(
            {
                "symbol": "VN30F1M",
                "bid": [{"price": 1000.0, "qtty": 5}],
                "offer": [{"price": 1000.5, "qtty": 7}],
                "receivedAt": 1735783200.0,
            },
        ),
    )
    assert len(client.data) == 1
    assert client.data[0].bid_price == Price.from_str("1000.0")
    assert client.data[0].ask_price == Price.from_str("1000.5")

    asyncio.run(client._unsubscribe_quotes(command))
    assert len(trading.unsubscribes) == 7
    assert trading.unsubscribes[0] == ("top_price.G1.json", ["VN30F1M"])
    assert client._quote_symbols == set()


def test_dnse_trade_conversion_synthesizes_session_trade_id() -> None:
    trade = Trade.from_dict(
        {
            "symbol": "41I1G9000",
            "matchPrice": 1941.0,
            "matchQtty": 5,
            "totalVolumeTraded": 12345,
            "receivedAt": 1735783200.0,
        },
    )
    tick = dnse_trade_to_nautilus_trade_tick(trade, venue="HNX")
    assert tick.instrument_id == InstrumentId.from_str("41I1G9000.HNX")
    assert tick.price == Price.from_str("1941.0")
    assert tick.size == Quantity.from_int(5)
    assert tick.trade_id == TradeId("41I1G9000-12345")
    assert tick.aggressor_side == AggressorSide.NO_AGGRESSOR


def test_dnse_quote_conversion_builds_depth10_snapshot() -> None:
    levels = [{"price": 1940.6 + i * 0.1, "qtty": 3 + i} for i in range(3)]
    quote = Quote.from_dict(
        {
            "symbol": "41I1G9000",
            "bid": levels,
            "offer": [{"price": 1941.0 + i * 0.1, "qtty": 44 + i} for i in range(3)],
            "receivedAt": 1735783200.0,
        },
    )
    depth = dnse_quote_to_nautilus_depth10(quote, venue="HNX")
    assert depth.instrument_id == InstrumentId.from_str("41I1G9000.HNX")
    assert len(depth.bids) == 10
    assert len(depth.asks) == 10
    assert depth.bids[0].price == Price.from_str("1940.6")
    assert depth.asks[0].price == Price.from_str("1941.0")
    assert depth.bids[3].size == Quantity.from_int(0)  # padded to ten levels
    assert depth.bid_counts[:3] == [3, 4, 5]
    assert depth.bid_counts[3:] == [0] * 7


def test_dnse_subscribe_trades_routes_sdk_events() -> None:
    client, trading, _ = _dnse_client()
    command = SimpleNamespace(
        instrument_id=build_bar_type_for_symbol("41I1G9000", "1", "HNX").instrument_id,
    )
    asyncio.run(client._subscribe_trades(command))
    assert len(trading.trade_subscriptions) == 1
    subscription = trading.trade_subscriptions[0]
    assert subscription["symbols"] == ["41I1G9000"]

    subscription["on_trade"](
        Trade.from_dict(
            {
                "symbol": "41I1G9000",
                "matchPrice": 1941.0,
                "matchQtty": 5,
                "totalVolumeTraded": 12345,
                "receivedAt": 1735783200.0,
            },
        ),
    )
    assert len(client.data) == 1
    assert client.data[0].trade_id == TradeId("41I1G9000-12345")

    asyncio.run(client._unsubscribe_trades(command))
    assert trading.unsubscribes[0][0] == "tick.G1.json"


def test_dnse_quote_stream_shared_between_quotes_and_depth10() -> None:
    client, trading, _ = _dnse_client()
    command = SimpleNamespace(
        instrument_id=build_bar_type_for_symbol("41I1G9000", "1", "HNX").instrument_id,
    )
    asyncio.run(client._subscribe_quotes(command))
    asyncio.run(client._subscribe_book_depth10(command))
    assert len(trading.quote_subscriptions) == 1  # one shared SDK stream

    asyncio.run(client._unsubscribe_quotes(command))
    assert not trading.unsubscribes  # depth10 still uses the stream

    asyncio.run(client._unsubscribe_book_depth10(command))
    assert trading.unsubscribes[0][0] == "top_price.G1.json"
