"""Behaviour tests for the Entrade/DNSE adapter.

Each test pins one behaviour a trader relies on (an order type reaching the broker as the
right HNX order, a fill surviving a network error, a bar arriving after a reconnect, ...).
Broker and market-data services are replaced by small fakes that reproduce the relevant
wire behaviour; nothing here talks to DNSE or Entrade.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
import requests
from dnse.websocket.models import Ohlc
from dnse.websocket.models import Quote
from dnse.websocket.models import Trade
from nautilus_trader.core import UUID4
from nautilus_trader.live import BarsResponse, InstrumentResponse, InstrumentsResponse
from nautilus_trader.model import (
    AccountBalance,
    AccountId,
    Bar,
    ClientOrderId,
    InstrumentId,
    MarketOrder,
    OrderBookDepth10,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    Price,
    Quantity,
    QuoteTick,
    StrategyId,
    TimeInForce,
    TradeId,
    TradeTick,
    TraderId,
    VenueOrderId,
)

from market_data.sources.dnse.transform import _bar_ts_init as catalog_bar_ts_init
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeAccount
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeApiError
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeClient
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeClientConfig
from nautilus_bridge.adapters.entrade.config import DnseDataClientConfig
from nautilus_bridge.adapters.entrade.config import EntradeExecClientConfig
from nautilus_bridge.adapters.entrade.data import (
    DnseLiveDataClient,
    SubscriptionKey,
    build_bar_type_for_symbol,
    dnse_ohlc_body_to_nautilus_bars,
    dnse_quote_to_nautilus_depth10,
    dnse_quote_to_nautilus_quote_tick,
    dnse_trade_to_nautilus_trade_tick,
)
from nautilus_bridge.adapters.entrade.execution import (
    EntradeExecutionClient,
    entrade_account_balance,
    entrade_order_parameters,
)
from nautilus_bridge.adapters.entrade.providers import DnseInstrumentProvider
from nautilus_bridge.adapters.entrade.providers import EntradeInstrumentProvider
from nautilus_bridge.instruments.currencies import VND
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1MResolver

NOW_NS = 1_800_000_000_000_000_000
CONTRACT_SYMBOL = "41I1G8000"
# 2025-01-02 09:00 Asia/Ho_Chi_Minh, a working day.
BAR_OPEN_S = 1_735_783_200


class FakeClock:
    def __init__(self, now_ns: int = NOW_NS) -> None:
        self.now_ns = now_ns

    def timestamp_ns(self) -> int:
        return self.now_ns


def _iso(ns: int) -> str:
    return pd.Timestamp(ns, tz="UTC").isoformat().replace("+00:00", "Z")


# --- DNSE market data --------------------------------------------------------------


class FakeDnseTradingClient:
    """Mimics the DNSE SDK: every subscribe call that passes a callback adds a handler."""

    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}
        self.subscriptions: list[tuple[str, dict]] = []
        self.unsubscribes: list[tuple[str, list[str]]] = []

    def on(self, event: str, handler: object) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, data: object) -> None:
        for handler in self.handlers.get(event, []):
            handler(data)

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def subscribe_ohlc_closed(self, on_ohlc=None, **kwargs: object) -> None:
        self.subscriptions.append(("ohlc_closed", kwargs))
        if on_ohlc:
            self.on("ohlc_closed", on_ohlc)

    async def subscribe_quotes(self, on_quote=None, **kwargs: object) -> None:
        self.subscriptions.append(("quote", kwargs))
        if on_quote:
            self.on("quote", on_quote)

    async def subscribe_trades(self, on_trade=None, **kwargs: object) -> None:
        self.subscriptions.append(("trade", kwargs))
        if on_trade:
            self.on("trade", on_trade)

    async def unsubscribe(self, channel: str, symbols: list[str]) -> None:
        self.unsubscribes.append((channel, symbols))


class FakeDnseRestClient:
    def get_instruments(self, **kwargs: object) -> tuple[int, str]:
        return 200, '{"data": []}'

    def __init__(
        self,
        status: int = 200,
        body: dict | None = None,
        failures_first: int = 0,
    ) -> None:
        self.status = status
        self.body = body
        self.failures_first = failures_first
        self.ohlc_calls: list[dict] = []

    def get_ohlc(self, **kwargs: object) -> tuple[int, dict]:
        self.ohlc_calls.append(kwargs)
        if len(self.ohlc_calls) <= self.failures_first:
            return 503, {"error": "unavailable"}
        return self.status, self.body or {
            "t": [BAR_OPEN_S, BAR_OPEN_S + 2 * 86_400],  # Thursday, Saturday
            "o": [1000.0, 990.0],
            "h": [1001.0, 991.0],
            "l": [999.0, 989.0],
            "c": [1000.5, 990.5],
            "v": [10, 5],
        }

    def get_working_dates(self, **kwargs: object) -> tuple[int, dict]:
        self.working_dates_calls += 1
        if self.working_dates_calls <= self.working_dates_failures_first:
            return 503, {"error": "unavailable"}
        return 200, {"workingDates": ["2025-01-02"]}

    working_dates_calls = 0
    working_dates_failures_first = 0


class FakeLog:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.records.append(("INFO", message))

    def warning(self, message: str) -> None:
        self.records.append(("WARNING", message))

    def error(self, message: str) -> None:
        self.records.append(("ERROR", message))

    def levels(self, level: str) -> list[str]:
        return [message for record_level, message in self.records if record_level == level]


class FakeReceiveTask:
    def __init__(self, done: bool) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


class RecordingDnseClient(DnseLiveDataClient):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.responses: list[object] = []
        self.instruments: list[object] = []
        self.data: list[object] = []
        self.tasks: list[tuple[str, object]] = []
        self._log = FakeLog()

    def run_tasks(self, prefix: str) -> None:
        """Run the scheduled background coroutines whose task name starts with prefix."""
        pending, self.tasks = self.tasks, []
        with patch("nautilus_bridge.adapters.entrade.data.asyncio.sleep", new=_no_sleep):
            for name, coroutine in pending:
                if name.startswith(prefix):
                    asyncio.run(coroutine)
                else:
                    self.tasks.append((name, coroutine))

    def _handle_response(self, response: object) -> None:
        self.responses.append(response)

    def _handle_instrument(self, instrument: object) -> None:
        self.instruments.append(instrument)

    def _handle_data(self, data: object) -> None:
        self.data.append(data)

    def create_task(self, coroutine, name: str = "background"):
        if name == "dnse_bar_watchdog":
            coroutine.close()  # the watchdog loop is exercised through _check_bar_watchdog
            return
        self.tasks.append((name, coroutine))


async def _no_sleep(seconds: float) -> None:
    return None


def _dnse_client(
    *,
    historical_source: str = "api",
    rest: FakeDnseRestClient | None = None,
    clock: FakeClock | None = None,
) -> tuple[RecordingDnseClient, FakeDnseTradingClient, FakeDnseRestClient]:
    config = DnseDataClientConfig(
        api_key="key",
        api_secret="secret",
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
        clock=clock or FakeClock(),
        venue="HNX",
        instrument_provider=DnseInstrumentProvider(config),
        trading_client=trading,
        rest_client=rest,
    )
    return client, trading, rest


def _ohlc(open_s: int, close: float, resolution: str = "1") -> Ohlc:
    return Ohlc.from_dict(
        {
            "symbol": "VN30F1M",
            "resolution": resolution,
            "open": close - 1,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "volume": 10,
            "time": open_s,
            "lastUpdated": open_s,
            "type": "ohlc",
        },
    )


def _quote(symbol: str, bid: float, board: str = "G1") -> Quote:
    return Quote.from_dict(
        {
            "symbol": symbol,
            "boardId": board,
            "bid": [{"price": bid, "qtty": 5}],
            "offer": [{"price": bid + 0.1, "qtty": 7}],
        },
    )


def _trade(symbol: str, board: str = "G1") -> Trade:
    return Trade.from_dict(
        {
            "symbol": symbol,
            "boardId": board,
            "matchPrice": 1941.0,
            "matchQtty": 5,
            "totalVolumeTraded": 12345,
        },
    )


def test_dnse_ohlc_conversion_preserves_prices_and_volume() -> None:
    bars = dnse_ohlc_body_to_nautilus_bars(
        {"t": [BAR_OPEN_S], "o": [1000.0], "h": [1001.0], "l": [999.0], "c": [1000.5], "v": [10]},
        symbol="VN30F1M",
        resolution="1",
        venue="HNX",
        working_dates=("2025-01-02",),
    )

    assert len(bars) == 1
    assert bars[0].bar_type == build_bar_type_for_symbol("VN30F1M", "1", "HNX")
    assert bars[0].open == Price.from_str("1000.0")
    assert bars[0].close == Price.from_str("1000.5")
    assert bars[0].volume == Quantity.from_int(10)


@pytest.mark.parametrize(
    ("local_open", "resolution"),
    [("09:00", "1"), ("11:29", "1"), ("14:29", "1"), ("14:45", "1"), ("09:00", "5")],
)
def test_live_bar_is_released_at_the_same_time_as_the_catalog_bar(
    local_open: str,
    resolution: str,
) -> None:
    """Live bars get the same ts_init as the catalog bars built by market_data."""
    open_utc = pd.Timestamp(f"2025-01-02 {local_open}", tz="Asia/Ho_Chi_Minh").tz_convert("UTC")
    [bar] = dnse_ohlc_body_to_nautilus_bars(
        {
            "t": [int(open_utc.timestamp())],
            "o": [1000.0],
            "h": [1001.0],
            "l": [999.0],
            "c": [1000.5],
            "v": [10],
        },
        symbol="VN30F1M",
        resolution=resolution,
        venue="HNX",
        working_dates=("2025-01-02",),
    )

    assert bar.ts_event == open_utc.value
    if resolution == "1":
        assert bar.ts_init == catalog_bar_ts_init(open_utc, open_utc.value)
    else:
        assert bar.ts_init == open_utc.value + 5 * 60 * 1_000_000_000


def test_dnse_closed_bars_skip_weekends_and_repeated_bars() -> None:
    client, trading, _ = _dnse_client()
    asyncio.run(client._connect())
    bar_type = build_bar_type_for_symbol("VN30F1M", "1", "HNX")
    asyncio.run(client._subscribe_bars(SimpleNamespace(bar_type=bar_type)))

    for open_s, close in (
        (BAR_OPEN_S + 2 * 86_400, 990.5),  # 2025-01-04 is a Saturday
        (BAR_OPEN_S, 1000.5),
        (BAR_OPEN_S, 1001.5),  # same bar again
        (BAR_OPEN_S + 60, 1002.5),
    ):
        trading.emit("ohlc_closed", _ohlc(open_s, close))

    published = [data for data in client.data if isinstance(data, Bar)]
    assert [bar.close.as_decimal() for bar in published] == [
        Decimal("1000.5"),
        Decimal("1002.5"),
    ]


def test_bars_missed_during_a_disconnect_are_recovered_without_a_strategy_request() -> None:
    """After a reconnect the missed bars arrive first, then the live stream resumes."""
    minute = 60
    rest = FakeDnseRestClient(
        body={
            "t": [BAR_OPEN_S + minute * i for i in range(4)],
            "o": [1000.0, 1001.0, 1002.0, 1003.0],
            "h": [1004.0] * 4,
            "l": [999.0] * 4,
            "c": [1000.0, 1001.0, 1002.0, 1003.0],
            "v": [10] * 4,
        },
    )
    # The node clock sits inside minute 3, so that bar is still forming and must not be served.
    clock = FakeClock((BAR_OPEN_S + 3 * minute + 30) * 1_000_000_000)
    client, trading, _ = _dnse_client(rest=rest, clock=clock)
    asyncio.run(client._connect())
    bar_type = build_bar_type_for_symbol("VN30F1M", "1", "HNX")
    asyncio.run(client._subscribe_bars(SimpleNamespace(bar_type=bar_type)))

    trading.emit("ohlc_closed", _ohlc(BAR_OPEN_S, 1000.0))
    trading.emit("reconnected", {"session_id": "next"})
    # A live bar arriving while the gap is being fetched waits its turn.
    trading.emit("ohlc_closed", _ohlc(BAR_OPEN_S + 3 * minute, 1003.0))
    assert len(client.data) == 1

    client.run_tasks("dnse_recover_bars")

    closes = [bar.close.as_decimal() for bar in client.data]
    assert closes == [Decimal("1000.0"), Decimal("1001.0"), Decimal("1002.0"), Decimal("1003.0")]
    assert rest.ohlc_calls[0]["query"]["from"] == BAR_OPEN_S


@pytest.mark.parametrize(("failures_first", "recovered"), [(2, True), (3, False)])
def test_bar_recovery_retries_three_times_before_reporting_an_error(
    failures_first: int,
    recovered: bool,
) -> None:
    rest = FakeDnseRestClient(
        failures_first=failures_first,
        body={"t": [BAR_OPEN_S + 60], "o": [1001.0], "h": [1002.0], "l": [1000.0], "c": [1001.0], "v": [10]},
    )
    client, trading, _ = _dnse_client(rest=rest, clock=FakeClock((BAR_OPEN_S + 150) * 1_000_000_000))
    asyncio.run(client._connect())
    bar_type = build_bar_type_for_symbol("VN30F1M", "1", "HNX")
    asyncio.run(client._subscribe_bars(SimpleNamespace(bar_type=bar_type)))
    trading.emit("ohlc_closed", _ohlc(BAR_OPEN_S, 1000.0))

    trading.emit("reconnected", {})
    trading.emit("ohlc_closed", _ohlc(BAR_OPEN_S + 120, 1002.0))
    client.run_tasks("dnse_recover_bars")

    closes = [bar.close.as_decimal() for bar in client.data]
    expected = ["1000.0", "1001.0", "1002.0"] if recovered else ["1000.0", "1002.0"]
    assert closes == [Decimal(value) for value in expected]
    assert len(rest.ohlc_calls) == min(failures_first + 1, 3)
    assert bool(client._log.levels("ERROR")) is not recovered


def test_sdk_error_is_an_error_only_when_the_receive_loop_has_stopped() -> None:
    client, trading, _ = _dnse_client()
    asyncio.run(client._connect())

    trading._message_handler_task = FakeReceiveTask(done=False)
    trading.emit("error", ConnectionError("connection reset"))
    client.run_tasks("dnse_stream_check")
    assert client._log.levels("ERROR") == []
    assert len(client._log.levels("WARNING")) == 1

    trading._message_handler_task = FakeReceiveTask(done=True)
    trading.emit("error", ConnectionError("reconnect failed"))
    trading.emit("max_reconnect_exceeded", 11)
    client.run_tasks("dnse_stream_check")
    [error] = client._log.levels("ERROR")
    assert "stopped" in error


def _local_ns(local: str) -> int:
    return pd.Timestamp(local, tz="Asia/Ho_Chi_Minh").value


@pytest.mark.parametrize(
    ("last_bar_local", "now_local", "expect_error"),
    [
        ("2025-01-02 10:00:30", "2025-01-02 10:03:00", False),  # 2.5 minutes
        ("2025-01-02 10:00:30", "2025-01-02 10:03:31", True),
        ("2025-01-02 11:29:05", "2025-01-02 12:15:00", False),  # lunch break
        ("2025-01-02 11:29:05", "2025-01-02 13:02:30", False),  # counted from 13:00
        ("2025-01-02 11:29:05", "2025-01-02 13:03:00", True),
        (None, "2025-01-02 09:03:00", True),  # nothing since the session opened
        ("2025-01-02 14:29:05", "2025-01-02 14:40:00", False),  # after the continuous session
        (None, "2025-01-03 10:30:00", False),  # not a working date
    ],
)
def test_bar_watchdog_reports_missing_minute_bars_only_during_sessions(
    last_bar_local: str | None,
    now_local: str,
    expect_error: bool,
) -> None:
    clock = FakeClock()
    client, trading, _ = _dnse_client(clock=clock)
    asyncio.run(client._connect())
    bar_type = build_bar_type_for_symbol("VN30F1M", "1", "HNX")
    asyncio.run(client._subscribe_bars(SimpleNamespace(bar_type=bar_type)))
    if last_bar_local is not None:
        clock.now_ns = _local_ns(last_bar_local)
        trading.emit("ohlc_closed", _ohlc(BAR_OPEN_S, 1000.0))

    asyncio.run(client._check_bar_watchdog(_local_ns(now_local)))
    asyncio.run(client._check_bar_watchdog(_local_ns(now_local)))  # a stall is reported once

    assert len(client._log.levels("ERROR")) == (1 if expect_error else 0)


def test_each_quote_and_trade_is_published_once_and_only_from_the_main_board() -> None:
    client, trading, _ = _dnse_client()
    asyncio.run(client._connect())
    front = SimpleNamespace(instrument_id=InstrumentId.from_str("41I1G8000.HNX"))
    back = SimpleNamespace(instrument_id=InstrumentId.from_str("41I1G9000.HNX"))
    for command in (front, back):
        asyncio.run(client._subscribe_quotes(command))
        asyncio.run(client._subscribe_trades(command))
    asyncio.run(client._subscribe_book_depth(front))

    trading.emit("quote", _quote("41I1G8000", 1940.0))
    trading.emit("quote", _quote("41I1G8000", 1939.0, board="T1"))  # a board other than G1
    trading.emit("trade", _trade("41I1G9000"))
    trading.emit("trade", _trade("41I1G9000", board="T3"))

    assert [type(data) for data in client.data] == [QuoteTick, OrderBookDepth10, TradeTick]
    # The installed SDK resubscribes only the last symbol list sent per channel.
    quote_subscriptions = [kwargs for kind, kwargs in trading.subscriptions if kind == "quote"]
    assert quote_subscriptions[-1]["symbols"] == ["41I1G8000", "41I1G9000"]
    assert {kwargs["board_id"] for kind, kwargs in trading.subscriptions if kind != "ohlc_closed"} == {"G1"}


def test_unsubscribing_stops_exactly_the_channels_that_were_subscribed() -> None:
    client, trading, _ = _dnse_client()
    asyncio.run(client._connect())
    command = SimpleNamespace(instrument_id=InstrumentId.from_str("41I1G8000.HNX"))
    asyncio.run(client._subscribe_quotes(command))
    asyncio.run(client._subscribe_book_depth(command))
    asyncio.run(client._subscribe_trades(command))

    asyncio.run(client._unsubscribe_quotes(command))
    assert trading.unsubscribes == []  # the order book still needs the quote stream
    asyncio.run(client._unsubscribe_book_depth(command))
    asyncio.run(client._unsubscribe_trades(command))

    assert trading.unsubscribes == [
        ("top_price.G1.json", ["41I1G8000"]),
        ("tick.G1.json", ["41I1G8000"]),
    ]
    trading.emit("quote", _quote("41I1G8000", 1940.0))
    trading.emit("trade", _trade("41I1G8000"))
    assert client.data == []


def test_quote_and_depth_conversion_keep_the_book_levels() -> None:
    quote = Quote.from_dict(
        {
            "symbol": "41I1G9000",
            "bid": [{"price": 1940.6 - i * 0.1, "qtty": 3 + i} for i in range(3)],
            "offer": [{"price": 1941.0 + i * 0.1, "qtty": 44 + i} for i in range(3)],
        },
    )
    tick = dnse_quote_to_nautilus_quote_tick(quote, venue="HNX")
    depth = dnse_quote_to_nautilus_depth10(quote, venue="HNX")

    assert (tick.bid_price, tick.ask_price) == (Price.from_str("1940.6"), Price.from_str("1941.0"))
    assert (tick.bid_size, tick.ask_size) == (Quantity.from_int(3), Quantity.from_int(44))
    assert [level.price for level in depth.bids[:3]] == [
        Price.from_str("1940.6"),
        Price.from_str("1940.5"),
        Price.from_str("1940.4"),
    ]
    assert depth.bids[3].size == Quantity.from_int(0)  # padded to ten levels


def test_trade_conversion_uses_the_session_volume_as_trade_id() -> None:
    tick = dnse_trade_to_nautilus_trade_tick(_trade("41I1G9000"), venue="HNX")

    assert tick.price == Price.from_str("1941.0")
    assert tick.size == Quantity.from_int(5)
    assert tick.trade_id == TradeId("41I1G9000-12345")


def test_historical_bar_request_answers_through_the_typed_response() -> None:
    client, _, rest = _dnse_client()
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

    assert len(rest.ohlc_calls) == 1
    [response] = client.responses
    assert isinstance(response, BarsResponse)
    assert response.correlation_id == request.request_id
    assert [bar.bar_type for bar in response.data] == [bar_type]


def _client_without_working_dates(
    rest: FakeDnseRestClient,
) -> tuple[RecordingDnseClient, FakeDnseTradingClient]:
    config = DnseDataClientConfig(api_key="key", api_secret="secret", historical_source="api")
    trading = FakeDnseTradingClient()
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
    with patch("nautilus_bridge.adapters.entrade.data.asyncio.sleep", new=_no_sleep):
        asyncio.run(client._connect())
    asyncio.run(
        client._subscribe_bars(
            SimpleNamespace(bar_type=build_bar_type_for_symbol("VN30F1M", "1", "HNX")),
        ),
    )
    return client, trading


def test_working_dates_are_retried_at_connect() -> None:
    rest = FakeDnseRestClient()
    rest.working_dates_failures_first = 2

    client, _ = _client_without_working_dates(rest)

    assert client._market_working_dates == ("2025-01-02",)
    assert client._log.levels("WARNING") == []


def test_watchdog_reloads_working_dates_that_failed_at_connect() -> None:
    rest = FakeDnseRestClient()
    rest.working_dates_failures_first = 3  # every attempt at connect fails
    client, _ = _client_without_working_dates(rest)
    assert len(client._log.levels("WARNING")) == 1

    # 2025-01-03 is a Friday that is not in the list, i.e. a holiday.
    asyncio.run(client._check_bar_watchdog(_local_ns("2025-01-03 10:30:00")))

    assert client._market_working_dates == ("2025-01-02",)
    assert client._log.levels("ERROR") == []


@pytest.mark.parametrize(
    ("ohlc_status", "bar_times", "expect_error"),
    [
        (200, [1735873200], True),  # 2025-01-03 10:00 local: market open, stream stalled
        (200, [1735783200], False),  # only yesterday's bar: market closed today
        (503, [], True),  # REST unreachable: cannot confirm a closed market
    ],
)
def test_watchdog_without_working_dates_asks_rest_whether_the_market_traded_today(
    ohlc_status: int,
    bar_times: list[int],
    expect_error: bool,
) -> None:
    rest = FakeDnseRestClient(
        status=ohlc_status,
        body={
            "t": bar_times,
            "o": [1000.0] * len(bar_times),
            "h": [1001.0] * len(bar_times),
            "l": [999.0] * len(bar_times),
            "c": [1000.5] * len(bar_times),
            "v": [10] * len(bar_times),
        } if bar_times else {"error": "unavailable"},
    )
    rest.working_dates_failures_first = 10**6  # the list never loads
    client, _ = _client_without_working_dates(rest)

    asyncio.run(client._check_bar_watchdog(_local_ns("2025-01-03 10:30:00")))
    calls_after_first_check = len(rest.ohlc_calls)
    asyncio.run(client._check_bar_watchdog(_local_ns("2025-01-03 10:31:00")))

    assert len(client._log.levels("ERROR")) == (1 if expect_error else 0)
    if not expect_error:
        # A closed day is decided once; later checks that day do not call REST again.
        assert len(rest.ohlc_calls) == calls_after_first_check


def test_bars_of_days_before_the_dnse_working_date_list_are_kept() -> None:
    """The DNSE working-date list starts at the current day; earlier bars must not be dropped."""
    config = DnseDataClientConfig(
        api_key="key",
        api_secret="secret",
        historical_source="api",
        market_working_dates=("2025-01-03", "2025-01-06"),  # the list as DNSE returns it on 01-03
    )
    client = RecordingDnseClient(
        name="DNSE",
        config=config,
        cache=None,
        clock=FakeClock(),
        venue="HNX",
        instrument_provider=DnseInstrumentProvider(config),
        trading_client=FakeDnseTradingClient(),
        rest_client=FakeDnseRestClient(),
    )
    bar_type = build_bar_type_for_symbol("VN30F1M", "1", "HNX")
    request = SimpleNamespace(
        request_id=UUID4(),
        bar_type=bar_type,
        start=datetime(2025, 1, 2, 2, tzinfo=UTC),
        end=datetime(2025, 1, 5, 2, tzinfo=UTC),
        start_ns=1735783200000000000,
        end_ns=1736042400000000000,
        params={},
    )

    asyncio.run(client._request_bars(request))

    [response] = client.responses
    assert [bar.ts_event for bar in response.data] == [BAR_OPEN_S * 1_000_000_000]


def test_instrument_requests_answer_and_api_failure_propagates() -> None:
    client, _, _ = _dnse_client()
    instrument_id = InstrumentId.from_str("VN30F1M.HNX")
    window = {"start": None, "end": None, "start_ns": None, "end_ns": None, "params": {}}
    asyncio.run(
        client._request_instrument(
            SimpleNamespace(request_id=UUID4(), instrument_id=instrument_id, **window),
        ),
    )
    asyncio.run(
        client._request_instruments(
            SimpleNamespace(request_id=UUID4(), venue=instrument_id.venue, **window),
        ),
    )
    assert [type(response) for response in client.responses] == [
        InstrumentResponse,
        InstrumentsResponse,
    ]

    failing, _, _ = _dnse_client(rest=FakeDnseRestClient(status=503, body={"error": "down"}))
    request = SimpleNamespace(
        request_id=UUID4(),
        bar_type=build_bar_type_for_symbol("VN30F1M", "1", "HNX"),
        start=datetime(2025, 1, 2, 2, tzinfo=UTC),
        end=datetime(2025, 1, 3, 2, tzinfo=UTC),
        start_ns=1735783200000000000,
        end_ns=1735869600000000000,
        params={},
    )
    with pytest.raises(ValueError, match="DNSE get_ohlc failed"):
        asyncio.run(failing._request_bars(request))


# --- Entrade execution --------------------------------------------------------------


def _broker_order(
    order_id: int,
    *,
    status: str,
    order_type: str = "MTL",
    quantity: int = 1,
    filled: int = 0,
    side: str = "NB",
    price: float = 0.0,
    created_ns: int = NOW_NS,
) -> dict:
    reports = [
        {
            "version": 1,
            "execType": "F",
            "lastQuantity": filled,
            "lastPrice": 1905.8,
            "modifiedDate": "2026-07-20T04:21:48.100Z",
        },
    ] if filled else []
    return {
        "id": order_id,
        "symbol": CONTRACT_SYMBOL,
        "side": side,
        "price": price,
        "quantity": quantity,
        "orderType": order_type,
        "orderStatus": status,
        "fillQuantity": filled,
        "averagePrice": 1905.8 if filled else 0,
        "tradingFee": 15_750 * filled,
        "tradingTax": 0,
        "createdDate": _iso(created_ns),
        "modifiedDate": _iso(created_ns),
        "reports": reports,
    }


class FakeEntradeClient:
    def __init__(self) -> None:
        self.qmax = 10
        self.buying_power_calls = 0
        self.order_requests: list[dict] = []
        self.orders: dict[int, dict] = {}
        self.deals: list[dict] = []
        self.cancel_calls: list[str] = []
        self.place_response: dict | Exception | None = None
        self.get_order_errors: list[Exception] = []
        self.cancel_errors: dict[str, Exception] = {}
        self.next_id = 7001
        self.derivatives = [
            {
                "symbol": CONTRACT_SYMBOL,
                "type": "VN30F2M",
                "expirationDate": "2027-08-20T00:00:00.000Z",
                "marketPrice": 1535.2,
            },
        ]
        self.get_order_calls = 0

    def authenticate(self, username: str, password: str) -> str:
        claims = base64.urlsafe_b64encode(json.dumps({"investorId": 123}).encode()).decode()
        return f"header.{claims.rstrip('=')}.signature"

    def get_account_balance(self, investor_id: int | str) -> dict:
        return {"investorAccountId": 456, "nav": 100_000_000, "availableCash": 90_000_000}

    def list_margin_portfolios(self, investor_id: int | str) -> dict:
        return {"data": [{"id": 32}]}

    def list_derivatives(self) -> dict:
        return {"data": self.derivatives}

    def get_buying_power(self, **kwargs: object) -> dict:
        self.buying_power_calls += 1
        return {"qmax": self.qmax}

    def place_order(self, **kwargs: object) -> dict:
        self.order_requests.append(kwargs)
        if isinstance(self.place_response, Exception):
            raise self.place_response
        if self.place_response is not None:
            payload = self.place_response
        else:
            payload = _broker_order(
                self.next_id,
                status="Filled",
                order_type=str(kwargs["order_type"]),
                quantity=int(kwargs["quantity"]),
                filled=int(kwargs["quantity"]),
                side=str(kwargs["side"]),
            )
            self.next_id += 1
        self.orders[payload["id"]] = payload
        return payload

    def get_order(self, order_id: int | str) -> dict:
        self.get_order_calls += 1
        if self.get_order_errors:
            raise self.get_order_errors.pop(0)
        return self.orders[int(order_id)]

    def cancel_order(self, order_id: int | str) -> dict:
        self.cancel_calls.append(str(order_id))
        if str(order_id) in self.cancel_errors:
            raise self.cancel_errors[str(order_id)]
        order = {**self.orders[int(order_id)], "orderStatus": "Canceled"}
        self.orders[int(order_id)] = order
        return order

    def list_all_orders(self, **kwargs: object) -> list[dict]:
        return list(self.orders.values())

    def list_all_deals(self, **kwargs: object) -> list[dict]:
        return self.deals

    def close(self) -> None:
        return None


class RecordingEntradeClient(EntradeExecutionClient):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.events: list[tuple[str, tuple]] = []

    def create_task(self, coroutine, name: str = "background"):
        coroutine.close()

    def _generate_balance(self, payload: dict) -> None:
        self.events.append(("account_state", ()))

    def _handle_instrument(self, instrument: object) -> None:
        return None

    def _record(name: str):  # noqa: N805 - builds recording methods below
        def record(self, *args: object) -> None:
            self.events.append((name, args))

        return record

    generate_order_denied = _record("denied")
    generate_order_submitted = _record("submitted")
    generate_order_accepted = _record("accepted")
    generate_order_updated = _record("updated")
    generate_order_filled = _record("filled")
    generate_order_rejected = _record("rejected")
    generate_order_canceled = _record("canceled")
    generate_order_expired = _record("expired")
    generate_order_modify_rejected = _record("modify_rejected")
    generate_order_cancel_rejected = _record("cancel_rejected")

    def names(self) -> list[str]:
        return [name for name, _ in self.events if name != "account_state"]


def _entrade_client(
    tmp_path: Path,
    *,
    api: FakeEntradeClient | None = None,
    clock: FakeClock | None = None,
    account_id: str = "ENTRADE-456",
    cache: object = None,
    continuous: bool = False,
) -> tuple[RecordingEntradeClient, FakeEntradeClient]:
    api = api or FakeEntradeClient()
    provider = EntradeInstrumentProvider(api)
    config = EntradeExecClientConfig(
        username="user",
        password="password",
        account_id=account_id,
        account=EntradeAccount.DEMO,
    )
    client = RecordingEntradeClient(
        name="ENTRADE",
        config=config,
        cache=cache,
        clock=clock or FakeClock(),
        trader_id=TraderId("TRADER-001"),
        instrument_provider=provider,
        client=api,
        symbol_resolver=VN30F1MResolver(provider.list_all) if continuous else None,
    )
    asyncio.run(client._connect())
    return client, api


def _market_order(
    coid: str,
    *,
    instrument_id: str = f"{CONTRACT_SYMBOL}.HNX",
    quantity: int = 1,
    time_in_force: TimeInForce = TimeInForce.GTC,
    reduce_only: bool = False,
    side: OrderSide = OrderSide.BUY,
) -> MarketOrder:
    return MarketOrder(
        TraderId("TRADER-001"),
        StrategyId("S-001"),
        InstrumentId.from_str(instrument_id),
        ClientOrderId(coid),
        side,
        Quantity.from_int(quantity),
        UUID4(),
        1,
        time_in_force,
        reduce_only,
        False,
    )


def _submit(client: RecordingEntradeClient, order: MarketOrder) -> None:
    asyncio.run(client._submit_order(SimpleNamespace(order=order)))


@pytest.mark.parametrize(
    ("order_type", "time_in_force", "expected"),
    [
        # MARKET with GTC/DAY (GTC is the Nautilus default) is sent as MTL.
        (OrderType.MARKET, TimeInForce.GTC, "MTL"),
        (OrderType.MARKET, TimeInForce.DAY, "MTL"),
        (OrderType.MARKET, TimeInForce.IOC, "MAK"),
        (OrderType.MARKET, TimeInForce.FOK, "MOK"),
        (OrderType.MARKET_TO_LIMIT, TimeInForce.GTC, "MTL"),
        # LIMIT with DAY, GTC or GTD is sent as LO.
        (OrderType.LIMIT, TimeInForce.DAY, "LO"),
        (OrderType.LIMIT, TimeInForce.GTC, "LO"),
        (OrderType.LIMIT, TimeInForce.GTD, "LO"),
        (OrderType.LIMIT, TimeInForce.IOC, None),
        (OrderType.LIMIT, TimeInForce.FOK, None),
        (OrderType.STOP_MARKET, TimeInForce.GTC, None),
    ],
)
def test_nautilus_order_becomes_the_matching_hnx_order(
    order_type: OrderType,
    time_in_force: TimeInForce,
    expected: str | None,
) -> None:
    order = SimpleNamespace(
        side=OrderSide.SELL,
        quantity=Quantity.from_int(2),
        order_type=order_type,
        time_in_force=time_in_force,
        price=Price.from_str("1900.5"),
    )
    if expected is None:
        with pytest.raises(ValueError, match="no HNX equivalent"):
            entrade_order_parameters(order)
        return

    side, wire_type, quantity, price = entrade_order_parameters(order)
    assert (side, wire_type, quantity) == ("NS", expected, 2)
    assert price == (1900.5 if expected == "LO" else 0.0)


def test_default_market_order_is_sent_as_mtl_and_fills(tmp_path: Path) -> None:
    client, api = _entrade_client(tmp_path)

    _submit(client, _market_order("O-1"))

    assert api.order_requests[0]["order_type"] == "MTL"
    assert client.names() == ["submitted", "accepted", "filled"]


def _two_contract_client(tmp_path: Path, local_now: str):
    api = FakeEntradeClient()
    api.derivatives = [
        {"symbol": "41I1FA000", "type": "VN30F1M", "expirationDate": "2026-10-15T00:00:00.000Z", "marketPrice": 1900.0},
        {"symbol": "41I1FB000", "type": "VN30F2M", "expirationDate": "2026-11-19T00:00:00.000Z", "marketPrice": 1905.0},
    ]
    now = pd.Timestamp(local_now, tz="Asia/Ho_Chi_Minh").value
    return _entrade_client(tmp_path, api=api, clock=FakeClock(now), continuous=True)


@pytest.mark.parametrize(
    ("local_now", "expected_contract"),
    [
        ("2026-10-15 14:00", "41I1FA000"),  # expiry day, before 14:45
        ("2026-10-15 15:00", "41I1FB000"),  # expiry day, after 14:45
        ("2026-10-16 09:00", "41I1FB000"),
    ],
)
def test_vn30f1m_order_goes_to_the_front_month_and_reports_back_as_vn30f1m(
    tmp_path: Path,
    local_now: str,
    expected_contract: str,
) -> None:
    client, api = _two_contract_client(tmp_path, local_now)
    api.deals = [
        {"id": 1, "symbol": expected_contract, "side": "NB", "openQuantity": 2,
         "positionCostPrice": "1900.0", "status": "ACTIVE", "modifiedDate": "2026-10-15T02:00:00.000Z"},
    ]

    _submit(client, _market_order("O-1", instrument_id="VN30F1M.HNX"))
    [position] = asyncio.run(
        client._generate_position_status_reports(
            SimpleNamespace(instrument_id=InstrumentId.from_str("VN30F1M.HNX")),
        ),
    )

    assert api.order_requests[0]["symbol"] == expected_contract
    assert client.names() == ["submitted", "accepted", "filled"]
    assert position.quantity == Quantity.from_int(2)


def test_unsupported_order_is_denied_without_reaching_the_broker(tmp_path: Path) -> None:
    client, api = _entrade_client(tmp_path)

    _submit(client, _market_order("O-1", time_in_force=TimeInForce.AT_THE_CLOSE))

    assert api.order_requests == []
    assert client.names() == ["denied"]


def test_order_above_buying_power_is_denied_whole_instead_of_shrunk(tmp_path: Path) -> None:
    client, api = _entrade_client(tmp_path)
    api.qmax = 2

    _submit(client, _market_order("O-1", quantity=5))

    assert api.order_requests == []
    assert client.names() == ["denied"]
    assert "at most 2" in client.events[-1][1][1]


def test_closing_order_is_not_blocked_by_buying_power(tmp_path: Path) -> None:
    client, api = _entrade_client(tmp_path)
    api.qmax = 0

    _submit(client, _market_order("O-1", quantity=3, reduce_only=True, side=OrderSide.SELL))

    assert api.buying_power_calls == 0
    assert api.order_requests[0]["quantity"] == 3


def test_broker_refusal_is_reported_as_rejected(tmp_path: Path) -> None:
    client, api = _entrade_client(tmp_path)
    api.place_response = EntradeApiError(
        "Entrade returned HTTP 400",
        method="POST",
        url="orders",
        status_code=400,
        payload={"message": "Price out of band"},
    )

    _submit(client, _market_order("O-1"))

    assert client.names() == ["submitted", "rejected"]


def test_lost_submission_response_finds_the_order_at_the_broker(tmp_path: Path) -> None:
    """A timeout is not a rejection: the order may exist, so it is looked up instead."""
    clock = FakeClock()
    client, api = _entrade_client(tmp_path, clock=clock)
    api.place_response = EntradeApiError("timed out", method="POST", url="orders")

    _submit(client, _market_order("O-1"))
    assert client.names() == ["submitted"]

    # The order did reach Entrade and filled.
    api.orders[9001] = _broker_order(9001, status="Filled", filled=1, created_ns=clock.now_ns + 200_000_000)
    clock.now_ns += 2_000_000_000
    asyncio.run(client._resolve_unresolved_submissions())

    assert client.names() == ["submitted", "accepted", "filled"]
    assert client.events[-2][1][1] == VenueOrderId("9001")


def test_lost_submission_is_rejected_once_the_broker_never_shows_it(tmp_path: Path) -> None:
    clock = FakeClock()
    client, api = _entrade_client(tmp_path, clock=clock)
    api.place_response = EntradeApiError("timed out", method="POST", url="orders")
    # An older identical order must not be mistaken for the lost one.
    api.orders[8000] = _broker_order(8000, status="Filled", filled=1, created_ns=clock.now_ns - 60_000_000_000)

    _submit(client, _market_order("O-1"))
    clock.now_ns += 10_000_000_000
    asyncio.run(client._resolve_unresolved_submissions())
    assert client.names() == ["submitted"]

    clock.now_ns += 30_000_000_000
    asyncio.run(client._resolve_unresolved_submissions())
    assert client.names() == ["submitted", "rejected"]


def test_order_waiting_for_the_exchange_is_accepted_only_when_the_broker_says_new(
    tmp_path: Path,
) -> None:
    client, api = _entrade_client(tmp_path)
    api.place_response = _broker_order(7100, status="PendingNew")

    _submit(client, _market_order("O-1"))
    assert client.names() == ["submitted"]

    api.orders[7100] = _broker_order(7100, status="New")
    asyncio.run(client._poll_one(client._orders[ClientOrderId("O-1")]))
    assert client.names() == ["submitted", "accepted"]


def test_network_error_while_polling_does_not_lose_the_fill(tmp_path: Path) -> None:
    client, api = _entrade_client(tmp_path)
    api.place_response = _broker_order(7100, status="New")
    _submit(client, _market_order("O-1"))
    context = client._orders[ClientOrderId("O-1")]

    api.orders[7100] = _broker_order(7100, status="Filled", filled=1)
    api.get_order_errors.append(EntradeApiError("connection reset", method="GET", url="order"))
    asyncio.run(client._poll_one(context))
    asyncio.run(client._poll_one(context))

    assert client.names() == ["submitted", "accepted", "filled"]
    assert client._balance_stale is True  # the next poll cycle refreshes the account balance


def test_done_for_day_order_expires_and_stops_being_polled(tmp_path: Path) -> None:
    client, api = _entrade_client(tmp_path)
    api.place_response = _broker_order(7100, status="New", order_type="LO", price=1900.0)
    _submit(client, _market_order("O-1"))

    api.orders[7100] = _broker_order(7100, status="DoneForDay", order_type="LO", price=1900.0)
    asyncio.run(client._poll_one(client._orders[ClientOrderId("O-1")]))

    assert client.names() == ["submitted", "accepted", "expired"]
    lookups = api.get_order_calls
    with patch("nautilus_bridge.adapters.entrade.execution.asyncio.sleep", new=_stop_polling_on_second_sleep(client)):
        asyncio.run(client._poll_orders())
    assert api.get_order_calls == lookups


def _stop_polling_on_second_sleep(client: RecordingEntradeClient):
    calls = []

    async def sleep(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) >= 2:
            client._polling = False

    return sleep


def test_fill_seen_twice_is_reported_once(tmp_path: Path) -> None:
    client, api = _entrade_client(tmp_path)
    api.place_response = _broker_order(7100, status="New", quantity=2)
    _submit(client, _market_order("O-1", quantity=2))
    context = client._orders[ClientOrderId("O-1")]

    partial = _broker_order(7100, status="PartiallyFilled", quantity=2, filled=1)
    client._synchronize_order(partial, context)
    client._synchronize_order(partial, context)
    client._synchronize_order({**partial, "orderStatus": "Canceled"}, context)

    assert client.names() == ["submitted", "accepted", "filled", "canceled"]


def test_order_rebuilt_by_reconciliation_keeps_receiving_fills_and_can_be_canceled(
    tmp_path: Path,
) -> None:
    """After a restart Nautilus rebuilds a still-working order and registers it here."""
    rebuilt = SimpleNamespace(
        instrument_id=InstrumentId.from_str(f"{CONTRACT_SYMBOL}.HNX"),
        client_order_id=ClientOrderId("O-EXTERNAL-1"),
        venue_order_id=VenueOrderId("7100"),
        status=OrderStatus.ACCEPTED,
        is_open=True,
    )
    cache = SimpleNamespace(order=lambda client_order_id: rebuilt)
    client, api = _entrade_client(tmp_path, cache=cache)
    api.orders[7100] = _broker_order(7100, status="New", order_type="LO", quantity=2, price=1900.0)

    asyncio.run(
        client._register_external_order(
            rebuilt.client_order_id,
            rebuilt.venue_order_id,
            rebuilt.instrument_id,
            StrategyId("EXTERNAL"),
            0,
        ),
    )
    # One contract fills while the node is running again.
    api.orders[7100] = _broker_order(7100, status="PartiallyFilled", order_type="LO", quantity=2, filled=1, price=1900.0)
    asyncio.run(client._poll_one(client._orders[rebuilt.client_order_id]))
    asyncio.run(client._cancel_one(rebuilt, None))

    assert client.names() == ["filled", "canceled"]
    assert api.cancel_calls == ["7100"]


def test_cancel_all_keeps_going_after_one_cancel_fails(tmp_path: Path) -> None:
    open_orders: list = []
    cache = SimpleNamespace(orders_open=lambda **kwargs: open_orders)
    client, api = _entrade_client(tmp_path, cache=cache)
    for coid, broker_id in (("O-1", 7100), ("O-2", 7101)):
        api.place_response = _broker_order(broker_id, status="New", order_type="LO", price=1900.0)
        _submit(client, _market_order(coid))
    api.cancel_errors["7100"] = EntradeApiError("HTTP 500", method="DELETE", url="order", status_code=500)
    open_orders.extend(client._orders[ClientOrderId(coid)].order for coid in ("O-1", "O-2"))

    asyncio.run(
        client._cancel_all_orders(
            SimpleNamespace(instrument_id=None, order_side=OrderSide.NO_ORDER_SIDE),
        ),
    )

    assert api.cancel_calls == ["7100", "7101"]
    assert client.names()[-2:] == ["cancel_rejected", "canceled"]


def test_unknown_order_in_history_is_skipped_instead_of_blocking_startup(tmp_path: Path) -> None:
    client, api = _entrade_client(tmp_path)
    api.orders[1] = {**_broker_order(1, status="Filled", filled=1), "orderType": "CONDITIONAL"}
    api.orders[2] = _broker_order(2, status="Filled", order_type="MAK", filled=1)

    reports = asyncio.run(
        client._generate_order_status_reports(
            SimpleNamespace(instrument_id=None, open_only=False, start=None),
        ),
    )

    assert [report.venue_order_id for report in reports] == [VenueOrderId("2")]


def test_position_reports_answer_only_the_requested_contract_and_net_both_sides(
    tmp_path: Path,
) -> None:
    client, api = _entrade_client(tmp_path)
    api.deals = [
        {"id": 1, "symbol": CONTRACT_SYMBOL, "side": "NB", "openQuantity": 3,
         "positionCostPrice": "1900.0", "status": "ACTIVE", "modifiedDate": "2026-07-20T04:21:48.100Z"},
        {"id": 2, "symbol": CONTRACT_SYMBOL, "side": "NS", "openQuantity": 1,
         "positionCostPrice": "1910.0", "status": "ACTIVE", "modifiedDate": "2026-07-20T04:21:48.100Z"},
    ]

    [report] = asyncio.run(
        client._generate_position_status_reports(
            SimpleNamespace(instrument_id=InstrumentId.from_str(f"{CONTRACT_SYMBOL}.HNX")),
        ),
    )
    other = asyncio.run(
        client._generate_position_status_reports(
            SimpleNamespace(instrument_id=InstrumentId.from_str("VN30F1M.HNX")),
        ),
    )

    assert (report.position_side, report.quantity) == (PositionSide.LONG, Quantity.from_int(2))
    assert report.avg_px_open == Decimal("1900.0")
    assert other == []


def test_reports_carry_exact_broker_values(tmp_path: Path) -> None:
    client, api = _entrade_client(tmp_path)
    payload = _broker_order(7100, status="Filled", order_type="MAK", quantity=2, filled=2)

    status_report = client._order_status_report(payload)
    [fill] = client._fill_reports(payload)
    balance = entrade_account_balance({"nav": "100000000.00", "availableCash": "90000000.00"}, VND)

    assert status_report.order_status == OrderStatus.FILLED
    assert status_report.avg_px == Decimal("1905.8")
    assert fill.last_px == Price.from_str("1905.8")
    assert fill.commission.as_decimal() == 31_500
    assert isinstance(balance, AccountBalance)
    assert balance.locked.as_decimal() == 10_000_000


def test_connect_refuses_a_different_account_than_configured(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not match the authenticated account"):
        _entrade_client(tmp_path, account_id="ENTRADE-999")


# --- Entrade HTTP client ------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode()
        self.url = "https://services.entrade.com.vn/x"
        self.request = SimpleNamespace(method="GET")

    def json(self) -> object:
        return self._payload


class ScriptedSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def close(self) -> None:
        return None


def test_expired_token_signs_in_again_and_repeats_the_request_once() -> None:
    session = ScriptedSession(
        [
            FakeResponse(200, {"token": "first"}),
            FakeResponse(401, {"message": "token expired"}),
            FakeResponse(200, {"token": "second"}),
            FakeResponse(200, {"nav": 1}),
        ],
    )
    client = EntradeClient(EntradeClientConfig(), session=session)  # type: ignore[arg-type]
    client.authenticate("user", "password")

    assert client.get_account_balance(123) == {"nav": 1}
    assert [url.rsplit("/", 1)[-1] for _, url, _ in session.calls] == ["auth", "123", "auth", "123"]
    assert session.calls[-1][2]["headers"]["Authorization"] == "Bearer second"


def test_order_list_is_read_past_the_first_page() -> None:
    orders = [{"id": i} for i in range(250)]
    responses = [FakeResponse(200, {"data": orders[i : i + 100]}) for i in range(0, 300, 100)]
    session = ScriptedSession([FakeResponse(200, {"token": "t"}), *responses])
    client = EntradeClient(EntradeClientConfig(), session=session)  # type: ignore[arg-type]
    client.authenticate("user", "password")

    assert [order["id"] for order in client.list_all_orders(investor_account_id=456)] == list(range(250))


def test_order_list_stops_when_the_server_ignores_the_page_offset() -> None:
    page = {"data": [{"id": i} for i in range(100)]}
    session = ScriptedSession([FakeResponse(200, {"token": "t"}), FakeResponse(200, page), FakeResponse(200, page)])
    client = EntradeClient(EntradeClientConfig(), session=session)  # type: ignore[arg-type]
    client.authenticate("user", "password")

    assert len(client.list_all_orders(investor_account_id=456)) == 100


@pytest.mark.parametrize(
    ("account", "margin_portfolio_parameter"),
    [
        (EntradeAccount.DEMO, "bankMarginPortfolioId"),
        (EntradeAccount.LIVE, "bankMarginPortfolio"),
    ],
)
def test_buying_power_uses_the_parameter_name_of_each_account_kind(
    account: EntradeAccount,
    margin_portfolio_parameter: str,
) -> None:
    client = EntradeClient(EntradeClientConfig(account=account))

    with patch.object(client, "_request", return_value={}) as request:
        client.get_buying_power(
            investor_id=123,
            margin_portfolio_id=32,
            symbol=CONTRACT_SYMBOL,
            side="NB",
            price=1535.2,
        )

    assert request.call_args.kwargs["params"][margin_portfolio_parameter] == 32


def test_requests_exception_is_an_unknown_outcome_not_an_http_answer() -> None:
    """A transport failure carries no status code, which the submit path reads as 'unknown'."""

    class FailingSession(ScriptedSession):
        def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
            raise requests.ReadTimeout("read timed out")

    client = EntradeClient(EntradeClientConfig(), session=FailingSession([]))  # type: ignore[arg-type]
    client.set_token("t")

    with pytest.raises(EntradeApiError) as error:
        client.get_order(1)
    assert error.value.status_code is None



class FakeDnseRestClientWithContracts(FakeDnseRestClient):
    final_trade_dates = {"41I1GA000": "2026-10-15T00:00:00Z", "41I1GB000": "2026-11-19T00:00:00Z"}

    def get_instruments(self, **kwargs: object) -> tuple[int, str]:
        records = [
            {"symbol": "41I1GA000", "symbolType": "VN30F1M"},
            {"symbol": "41I1GB000", "symbolType": "VN30F2M"},
        ]
        return 200, json.dumps({"data": records})

    def get_security_definition(self, symbol: str, **kwargs: object) -> tuple[int, str]:
        return 200, json.dumps([{"finalTradeDate": self.final_trade_dates[symbol]}])


def test_vn30f1m_trades_follow_the_front_month_contract_through_expiry() -> None:
    def local_ns(*args: int) -> int:
        return int(pd.Timestamp(*args, tz="Asia/Ho_Chi_Minh").value)

    clock = FakeClock(local_ns(2026, 10, 15, 14, 44))
    client, trading, _ = _dnse_client(rest=FakeDnseRestClientWithContracts(), clock=clock)
    asyncio.run(client._connect())
    asyncio.run(client._subscribe_trades(SimpleNamespace(instrument_id=InstrumentId.from_str("VN30F1M.HNX"))))

    trading.emit("trade", _trade("41I1GA000"))
    clock.now_ns = local_ns(2026, 10, 15, 14, 46)
    asyncio.run(client._roll_streams())
    trading.emit("trade", _trade("41I1GA000"))
    trading.emit("trade", _trade("41I1GB000"))

    trade_symbols = [kwargs["symbols"] for kind, kwargs in trading.subscriptions if kind == "trade"]
    assert trade_symbols == [["41I1GA000"], ["41I1GB000"]]
    assert trading.unsubscribes == [("tick.G1.json", ["41I1GA000"])]
    assert [str(tick.instrument_id) for tick in client.data] == ["VN30F1M.HNX", "VN30F1M.HNX"]
