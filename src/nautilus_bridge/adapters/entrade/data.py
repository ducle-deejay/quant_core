from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from dnse import TradingClient
from dnse.websocket.models import Ohlc
from dnse.websocket.models import Quote
from dnse.websocket.models import Trade
from nautilus_trader.common import Logger
from nautilus_trader.live import (
    BarsResponse,
    ClientCache,
    DataClientConfig,
    InstrumentResponse,
    InstrumentsResponse,
    RequestBars,
    RequestCustomData,
    RequestInstrument,
    RequestInstruments,
    SubscribeBars,
    SubscribeCustomData,
    SubscribeInstrument,
    SubscribeInstruments,
    UnsubscribeBars,
    UnsubscribeCustomData,
    UnsubscribeInstrument,
    UnsubscribeInstruments,
)
from nautilus_trader.live.clients import MarketDataClient
from nautilus_trader.model import (
    AggregationSource,
    AggressorSide,
    Bar,
    BarAggregation,
    BarSpecification,
    BarType,
    BookOrder,
    InstrumentId,
    OrderBookDepth10,
    OrderSide,
    Price,
    PriceType,
    Quantity,
    QuoteTick,
    Symbol,
    TradeId,
    TradeTick,
    Venue,
)
from nautilus_trader.persistence import ParquetDataCatalog

from .config import DnseDataClientConfig
from .constants import ATC_LOCAL_MINUTE
from .constants import CONTINUOUS_SESSIONS_LOCAL
from .constants import DNSE_MAIN_BOARD
from .constants import NOT_IMPLEMENTED
from .constants import SUPPORTED_DNSE_RESOLUTIONS
from .constants import VN_TZ
from .api.dnse_api import close_dnse_rest_client
from .api.dnse_api import create_dnse_rest_client
from .providers import DnseInstrumentProvider

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CATALOG_PATH = REPO_ROOT / "data" / "catalog"
# Largest gap between the parsed DNSE time field and the local receipt time for which
# the DNSE time is used as ts_event; beyond it the receipt time is used.
MAX_EXCHANGE_CLOCK_GAP_NS = 60_000_000_000
SECOND_NS = 1_000_000_000
# Wait before checking whether the DNSE SDK receive loop survived an error event; the SDK
# emits "error" just before it stops that loop.
STREAM_CHECK_DELAY_SECONDS = 1.0
# During continuous sessions, no one-minute bar for this long is reported as an ERROR.
BAR_WATCHDOG_MINUTES = 3
BAR_WATCHDOG_INTERVAL_SECONDS = 60.0
# Waits between the attempts to fetch bars missed during a reconnect (three attempts).
BAR_RECOVERY_RETRY_DELAYS_SECONDS = (2.0, 5.0)
# Waits between the attempts to load the DNSE working-date list at connect (three attempts).
WORKING_DATES_RETRY_DELAYS_SECONDS = (2.0, 5.0)
_MISSING = object()


def normalize_dnse_resolution(resolution: str) -> str:
    normalized = resolution.upper()
    if normalized == "60":
        normalized = "1H"
    if normalized not in SUPPORTED_DNSE_RESOLUTIONS:
        raise ValueError(f"Unsupported DNSE resolution: {resolution}")
    return normalized


def dnse_resolution_to_bar_specification(resolution: str) -> BarSpecification:
    normalized = normalize_dnse_resolution(resolution)
    if normalized in {"1", "3", "5", "15", "30"}:
        return BarSpecification(int(normalized), BarAggregation.MINUTE, PriceType.LAST)
    if normalized == "1H":
        return BarSpecification(1, BarAggregation.HOUR, PriceType.LAST)
    if normalized == "1D":
        return BarSpecification(1, BarAggregation.DAY, PriceType.LAST)
    if normalized == "1W":
        return BarSpecification(1, BarAggregation.WEEK, PriceType.LAST)
    raise ValueError(f"Unsupported DNSE resolution: {resolution}")


def bar_type_to_dnse_resolution(bar_type: BarType) -> str:
    step = bar_type.spec.step
    aggregation = bar_type.spec.aggregation

    if aggregation == BarAggregation.MINUTE:
        return str(step)
    if aggregation == BarAggregation.HOUR and step == 1:
        return "1H"
    if aggregation == BarAggregation.DAY and step == 1:
        return "1D"
    if aggregation == BarAggregation.WEEK and step == 1:
        return "1W"

    raise ValueError(f"Unsupported bar type for DNSE OHLC subscription: {bar_type}")


def bar_interval_ns(bar_type: BarType) -> int:
    seconds_per_unit = {
        BarAggregation.MINUTE: 60,
        BarAggregation.HOUR: 3_600,
        BarAggregation.DAY: 86_400,
        BarAggregation.WEEK: 604_800,
    }
    return bar_type.spec.step * seconds_per_unit[bar_type.spec.aggregation] * SECOND_NS


def dnse_bar_ts_init(bar_type: BarType, ts_event: int, timezone_name: str = VN_TZ) -> int:
    """Return ``ts_init`` for a DNSE bar whose ``ts_event`` is the interval open.

    ``ts_init`` is the interval close, except for an intraday bar opening at 14:45
    (closing auction), which keeps ``ts_init == ts_event``. This is the same rule as
    ``_bar_ts_init`` in market_data/sources/dnse/transform.py.
    """
    if bar_type.spec.aggregation in (BarAggregation.MINUTE, BarAggregation.HOUR):
        local = pd.Timestamp(ts_event, tz="UTC").tz_convert(timezone_name)
        if (local.hour, local.minute) == ATC_LOCAL_MINUTE:
            return ts_event
    return ts_event + bar_interval_ns(bar_type)


def dnse_price(value: float, precision: int) -> Price:
    """Build a Price from a DNSE float through its shortest decimal text, not binary float."""
    return Price.from_decimal_dp(Decimal(str(value)), precision)


def dnse_quantity(value: float, precision: int) -> Quantity:
    return Quantity.from_decimal_dp(Decimal(str(value)), precision)


def dnse_epoch_to_utc_timestamp(value: float) -> pd.Timestamp:
    unit = "ms" if value >= 1_000_000_000_000 else "s"
    return pd.to_datetime(value, unit=unit, utc=True)  # type: ignore[call-overload]


def nautilus_datetime_to_utc_timestamp(
    value: datetime | pd.Timestamp | None,
) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def build_bar_type_for_symbol(
    symbol: str,
    resolution: str,
    venue: str,
) -> BarType:
    return BarType(
        InstrumentId(Symbol(symbol), Venue(venue)),
        dnse_resolution_to_bar_specification(resolution),
        AggregationSource.EXTERNAL,
    )


def dnse_exchange_time_ns(value: Any, timezone_name: str = VN_TZ) -> int | None:
    """Parse the DNSE ``time`` field of a quote or trade; None when it cannot be parsed.

    The format of this field has not been confirmed against live payloads. Epoch
    numbers and ISO text are accepted; text without an offset is read as Vietnam
    local time.
    """
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return int(dnse_epoch_to_utc_timestamp(value).value)
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(timezone_name)
        return int(timestamp.tz_convert("UTC").value)
    except (TypeError, ValueError):
        return None


def dnse_payload_timestamps(
    payload: Quote | Trade,
    timezone_name: str,
    fallback_ts_ns: int,
) -> tuple[int, int]:
    """Return (ts_event, ts_init): exchange time of the event and local receipt time."""
    ts_init = (
        int(payload.receivedAt * SECOND_NS) if payload.receivedAt else fallback_ts_ns
    )
    ts_event = dnse_exchange_time_ns(payload.time, timezone_name)
    if ts_event is None or abs(ts_init - ts_event) > MAX_EXCHANGE_CLOCK_GAP_NS:
        return ts_init, ts_init
    return ts_event, ts_init


def dnse_quote_to_nautilus_quote_tick(
    quote: Quote,
    venue: str,
    price_precision: int = 1,
    volume_precision: int = 0,
    timezone_name: str = VN_TZ,
    fallback_ts_ns: int = 0,
) -> QuoteTick:
    """Convert a DNSE top-of-book quote to a Nautilus QuoteTick."""
    best_bid = quote.best_bid
    best_ask = quote.best_ask
    if best_bid is None or best_ask is None:
        raise ValueError(f"DNSE quote for {quote.symbol} is missing a bid or ask")

    ts_event, ts_init = dnse_payload_timestamps(quote, timezone_name, fallback_ts_ns)
    return QuoteTick(
        instrument_id=InstrumentId(Symbol(quote.symbol), Venue(venue)),
        bid_price=dnse_price(best_bid[0], price_precision),
        ask_price=dnse_price(best_ask[0], price_precision),
        bid_size=dnse_quantity(best_bid[1], volume_precision),
        ask_size=dnse_quantity(best_ask[1], volume_precision),
        ts_event=ts_event,
        ts_init=ts_init,
    )


def dnse_levels_to_book_orders(
    levels,
    side: OrderSide,
    price_precision: int,
    volume_precision: int,
) -> tuple[list[BookOrder], list[int]]:
    orders = [
        BookOrder(
            side,
            dnse_price(level.price, price_precision),
            dnse_quantity(level.quantity, volume_precision),
            0,
        )
        for level in levels[:10]
    ]
    counts = [int(level.quantity) for level in levels[:10]]
    placeholder = BookOrder(None, Price(0, price_precision), Quantity(0, volume_precision), 0)
    while len(orders) < 10:
        orders.append(placeholder)
        counts.append(0)
    return orders, counts


def dnse_quote_to_nautilus_depth10(
    quote: Quote,
    venue: str,
    price_precision: int = 1,
    volume_precision: int = 0,
    timezone_name: str = VN_TZ,
    fallback_ts_ns: int = 0,
) -> OrderBookDepth10:
    """Convert a DNSE top-price payload (ten levels per side) to a Depth10 snapshot."""
    ts_event, ts_init = dnse_payload_timestamps(quote, timezone_name, fallback_ts_ns)
    bids, bid_counts = dnse_levels_to_book_orders(quote.bid, OrderSide.BUY, price_precision, volume_precision)
    asks, ask_counts = dnse_levels_to_book_orders(quote.offer, OrderSide.SELL, price_precision, volume_precision)
    # DNSE does not expose order counts per level; the level size stands in for it.
    return OrderBookDepth10(
        instrument_id=InstrumentId(Symbol(quote.symbol), Venue(venue)),
        bids=bids,
        asks=asks,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_init,
    )


def dnse_trade_to_nautilus_trade_tick(
    trade: Trade,
    venue: str,
    price_precision: int = 1,
    volume_precision: int = 0,
    timezone_name: str = VN_TZ,
    fallback_ts_ns: int = 0,
) -> TradeTick:
    """Convert a DNSE trade tick to a Nautilus TradeTick.

    DNSE exposes no aggressor side and no trade id; the session-cumulative
    ``totalVolumeTraded`` stands in as the unique per-session trade id.
    """
    ts_event, ts_init = dnse_payload_timestamps(trade, timezone_name, fallback_ts_ns)
    return TradeTick(
        instrument_id=InstrumentId(Symbol(trade.symbol), Venue(venue)),
        price=dnse_price(trade.price, price_precision),
        size=dnse_quantity(trade.quantity, volume_precision),
        aggressor_side=AggressorSide.NO_AGGRESSOR,
        trade_id=TradeId(f"{trade.symbol}-{trade.totalVolumeTraded}"),
        ts_event=ts_event,
        ts_init=ts_init,
    )


def dnse_ohlc_to_nautilus_bar(
    ohlc: Ohlc,
    venue: str,
    price_precision: int = 1,
    volume_precision: int = 0,
    timezone_name: str = VN_TZ,
) -> Bar:
    bar_type = build_bar_type_for_symbol(
        symbol=ohlc.symbol, resolution=ohlc.resolution, venue=venue
    )
    ts_event = int(dnse_epoch_to_utc_timestamp(ohlc.time).value)

    return Bar(
        bar_type,
        dnse_price(ohlc.open, price_precision),
        dnse_price(ohlc.high, price_precision),
        dnse_price(ohlc.low, price_precision),
        dnse_price(ohlc.close, price_precision),
        dnse_quantity(ohlc.volume, volume_precision),
        ts_event,
        dnse_bar_ts_init(bar_type, ts_event, timezone_name),
    )


def parse_dnse_ohlc_body(body: Any) -> dict[str, list[Any]]:
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict):
        raise ValueError(  # noqa: TRY004
            f"Unexpected DNSE OHLC response type: {type(body)}",
        )

    required_keys = ("t", "o", "h", "l", "c", "v")
    if not all(key in body for key in required_keys):
        raise ValueError(f"Unexpected DNSE OHLC response payload: {body}")
    return body


def parse_working_dates_body(body: Any) -> tuple[str, ...]:
    """Parse the DNSE working-date response payload."""
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict) or not isinstance(body.get("workingDates"), list):
        raise ValueError(f"Unexpected DNSE working dates payload: {body}")
    return tuple(str(value) for value in body["workingDates"])


def is_valid_vn_trading_day(
    timestamp_utc: pd.Timestamp,
    timezone_name: str = VN_TZ,
    working_dates: tuple[str, ...] | None = None,
) -> bool:
    """Return whether the timestamp belongs to an accepted VN trading date."""
    local_timestamp = timestamp_utc.tz_convert(timezone_name)
    if working_dates:
        return local_timestamp.date().isoformat() in set(working_dates)
    return local_timestamp.weekday() < 5


def dnse_ohlc_body_to_nautilus_bars(
    body: Any,
    symbol: str,
    resolution: str,
    venue: str,
    price_precision: int = 1,
    volume_precision: int = 0,
    timezone_name: str = VN_TZ,
    working_dates: tuple[str, ...] | None = None,
    drop_invalid_trading_days: bool = True,
) -> list[Bar]:
    parsed = parse_dnse_ohlc_body(body)
    bars: list[Bar] = []

    for timestamp_raw, open_raw, high_raw, low_raw, close_raw, volume_raw in zip(
        parsed["t"],
        parsed["o"],
        parsed["h"],
        parsed["l"],
        parsed["c"],
        parsed["v"],
        strict=False,
    ):
        timestamp = dnse_epoch_to_utc_timestamp(timestamp_raw)
        if drop_invalid_trading_days and not is_valid_vn_trading_day(
            timestamp,
            timezone_name=timezone_name,
            working_dates=working_dates,
        ):
            continue

        ohlc = Ohlc.from_dict(
            {
                "symbol": symbol,
                "resolution": normalize_dnse_resolution(resolution),
                "open": open_raw,
                "high": high_raw,
                "low": low_raw,
                "close": close_raw,
                "volume": volume_raw,
                "time": timestamp_raw,
                "lastUpdated": timestamp_raw,
                "type": "history",
            },
        )
        bars.append(
            dnse_ohlc_to_nautilus_bar(
                ohlc=ohlc,
                venue=venue,
                price_precision=price_precision,
                volume_precision=volume_precision,
                timezone_name=timezone_name,
            ),
        )

    bars.sort(key=lambda bar: bar.ts_event)
    return bars


def _load_catalog_bars(
    catalog: ParquetDataCatalog,
    bar_type: BarType,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> list[Bar]:
    """Query bars for a bar type within [start, end] from a ParquetDataCatalog.

    The catalog stores bars under ``data/bars/{bar_type}`` and filters on
    ``ts_init``, which market_data sets to the interval close (see
    ``dnse_bar_ts_init``).
    """
    try:
        bars = catalog.query_bars(
            identifiers=[str(bar_type)],
            start=None if start is None else int(start.value),
            end=None if end is None else int(end.value),
        )
    except (OSError, RuntimeError):
        bars = []
    return bars


def _with_bar_type(bars: list[Bar], bar_type: BarType) -> list[Bar]:
    if not bars or bars[0].bar_type == bar_type:
        return bars
    return [
        Bar(
            bar_type,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.ts_event,
            bar.ts_init,
        )
        for bar in bars
    ]


@dataclass(frozen=True)
class SubscriptionKey:
    """Composition key for a DNSE OHLC subscription."""

    symbol: str
    resolution: str


class DnseLiveDataClient(MarketDataClient):
    """Nautilus extension implementing live and historical DNSE market data."""

    def __init__(
        self,
        *,
        name: str = "DNSE",
        config: DataClientConfig,
        cache: ClientCache,
        clock: Any,
        venue: Venue | str | None = None,
        instrument_provider: DnseInstrumentProvider | None = None,
        trading_client: TradingClient | None = None,
        rest_client: Any | None = None,
    ) -> None:
        if not isinstance(config, DnseDataClientConfig):
            raise TypeError("Expected DnseDataClientConfig")
        super().__init__(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
            venue=Venue(venue or config.venue),
        )
        self._config = config
        self._trading_client = trading_client
        self._rest_client = rest_client
        self._catalog: ParquetDataCatalog | None = None
        catalog_path = (
            Path(config.catalog_path) if config.catalog_path else DEFAULT_CATALOG_PATH
        )
        if not catalog_path.is_absolute():
            catalog_path = REPO_ROOT / catalog_path
        self._catalog_path = catalog_path
        self._bar_types_by_key: dict[SubscriptionKey, BarType] = {}
        self._subscribed_keys: set[SubscriptionKey] = set()
        self._last_bar_ts_by_key: dict[SubscriptionKey, int] = {}
        self._recovering_keys: set[SubscriptionKey] = set()
        self._buffered_ohlc_by_key: dict[SubscriptionKey, list[Ohlc]] = {}
        self._registered_handlers = False
        self._market_working_dates: tuple[str, ...] = config.market_working_dates
        self._quote_stream_symbols: set[str] = set()
        self._quote_symbols: set[str] = set()
        self._book_symbols: set[str] = set()
        self._trade_symbols: set[str] = set()
        self._closing = False
        self._stream_stop_reported = False
        self._last_minute_bar_received_ns: int | None = None
        self._bar_stall_reported = False
        self._market_closed_date: str | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._log = Logger(type(self).__name__)

    async def _connect(self) -> None:
        # Clients are created on the node's event-loop thread; the network connection
        # is opened by connect() below.
        if self._trading_client is None:
            self._trading_client = TradingClient(
                api_key=self._config.api_key,
                api_secret=self._config.api_secret,
                base_url=self._config.ws_base_url,
                encoding=self._config.ws_encoding,
                auto_reconnect=self._config.auto_reconnect,
                max_retries=self._config.max_retries,
                heartbeat_interval=self._config.heartbeat_interval,
                timeout=self._config.timeout,
            )
        if self._rest_client is None:
            self._rest_client = create_dnse_rest_client(
                api_key=self._config.api_key,
                api_secret=self._config.api_secret,
                base_url=self._config.rest_base_url,
                api_version=self._config.api_version,
            )
        if self._catalog is None and self._config.historical_source == "catalog":
            self._catalog = ParquetDataCatalog(str(self._catalog_path))
        if self.instrument_provider is None:
            raise RuntimeError("The DNSE data client requires an instrument provider")
        await self.instrument_provider.initialize()
        if self._config.use_dnse_working_dates and not self._market_working_dates:
            delays = (*WORKING_DATES_RETRY_DELAYS_SECONDS, None)
            for delay in delays:
                try:
                    self._market_working_dates = await self._load_market_working_dates()
                    break
                except Exception as e:  # noqa: BLE001 - retried, then the watchdog falls back.
                    if delay is None:
                        self._log.warning(
                            f"DNSE working dates unavailable ({e}); the bar watchdog retries "
                            "loading them and asks the REST API whether bars exist today",
                        )
                        break
                    await asyncio.sleep(delay)
        if not self._registered_handlers:
            # In the installed DNSE SDK, each subscribe_* call given a callback registers
            # one more handler, so each handler is registered once here and subscribe
            # calls pass no callback.
            self._trading_client.on("ohlc_closed", self._on_ohlc_event)
            self._trading_client.on("quote", self._on_quote_event)
            self._trading_client.on("trade", self._on_trade_event)
            self._trading_client.on("reconnecting", self._on_reconnecting)
            self._trading_client.on("reconnected", self._on_reconnected)
            self._trading_client.on("max_reconnect_exceeded", self._on_stream_lost)
            self._trading_client.on("error", self._on_stream_error)
            self._registered_handlers = True
        await self._trading_client.connect()
        self._closing = False
        self._watchdog_task = self.create_task(self._run_bar_watchdog(), name="dnse_bar_watchdog")

        if self._config.publish_instruments_on_connect:
            self._publish_all_instruments()

    async def _disconnect(self) -> None:
        self._closing = True
        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            await asyncio.wait({self._watchdog_task}, timeout=STREAM_CHECK_DELAY_SECONDS)
        if self._trading_client is not None:
            await self._trading_client.disconnect()
        close_dnse_rest_client(self._rest_client)

    async def _subscribe(self, command: SubscribeCustomData) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _unsubscribe(self, command: UnsubscribeCustomData) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _subscribe_instruments(self, command: SubscribeInstruments) -> None:
        self._publish_all_instruments(command.venue)

    async def _subscribe_instrument(self, command: SubscribeInstrument) -> None:
        instrument = await self._ensure_instrument(command.instrument_id.symbol.value)
        self._handle_instrument(instrument)

    async def _unsubscribe_instruments(self, command: UnsubscribeInstruments) -> None:
        return None

    async def _unsubscribe_instrument(self, command: UnsubscribeInstrument) -> None:
        return None

    async def _subscribe_bars(self, command: SubscribeBars) -> None:
        resolution = bar_type_to_dnse_resolution(command.bar_type)
        symbol = command.bar_type.instrument_id.symbol.value
        key = SubscriptionKey(symbol=symbol, resolution=resolution)
        self._bar_types_by_key[key] = command.bar_type
        if key in self._subscribed_keys:
            return

        if self._trading_client is None:
            raise RuntimeError("DNSE data client is not connected")
        # The installed DNSE SDK stores one symbol list per channel (the last one sent)
        # and resubscribes that list after a reconnect, so each call sends every
        # symbol of the channel.
        symbols = sorted(
            {k.symbol for k in self._subscribed_keys if k.resolution == resolution} | {symbol},
        )
        await self._trading_client.subscribe_ohlc_closed(
            symbols=symbols,
            resolution=resolution,
            encoding=self._config.ws_encoding,
        )
        self._subscribed_keys.add(key)

    async def _unsubscribe_bars(self, command: UnsubscribeBars) -> None:
        resolution = bar_type_to_dnse_resolution(command.bar_type)
        symbol = command.bar_type.instrument_id.symbol.value
        key = SubscriptionKey(symbol=symbol, resolution=resolution)
        self._bar_types_by_key.pop(key, None)
        self._subscribed_keys.discard(key)
        self._last_bar_ts_by_key.pop(key, None)
        if self._trading_client is None:
            raise RuntimeError("DNSE data client is not connected")
        await self._trading_client.unsubscribe(
            f"ohlc_closed.{resolution}.{self._channel_suffix}",
            [symbol],
        )

    async def _request_data(self, request: RequestCustomData) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _request_instrument(self, request: RequestInstrument) -> None:
        instrument = await self._ensure_instrument(request.instrument_id.symbol.value)
        self._handle_response(
            InstrumentResponse(
                self.client_id,
                request.instrument_id,
                instrument,
                request.request_id,
                self.clock.timestamp_ns(),
                request.start_ns,
                request.end_ns,
                request.params,
            ),
        )

    async def _request_instruments(self, request: RequestInstruments) -> None:
        if self.instrument_provider is None:
            raise RuntimeError("The DNSE data client requires an instrument provider")
        await self.instrument_provider.initialize()
        venue = request.venue or self.venue
        instruments = [
            instrument
            for instrument in self.instrument_provider.get_all().values()
            if venue is None or instrument.id.venue == venue
        ]
        self._handle_response(
            InstrumentsResponse(
                self.client_id,
                venue,
                instruments,
                request.request_id,
                self.clock.timestamp_ns(),
                request.start_ns,
                request.end_ns,
                request.params,
            ),
        )

    async def _request_bars(self, request: RequestBars) -> None:
        resolution = bar_type_to_dnse_resolution(request.bar_type)
        start = nautilus_datetime_to_utc_timestamp(request.start)
        end = nautilus_datetime_to_utc_timestamp(request.end)
        key = SubscriptionKey(
            symbol=request.bar_type.instrument_id.symbol.value,
            resolution=resolution,
        )

        bars: list[Bar] = []
        source = "api"
        if self._config.historical_source == "catalog":
            if self._catalog is None:
                self._log.warning(
                    "historical_source=catalog but no catalog was constructed; "
                    "falling back to DNSE API",
                )
            else:
                try:
                    bars = _load_catalog_bars(
                        catalog=self._catalog,
                        bar_type=request.bar_type,
                        start=start,
                        end=end,
                    )
                except Exception as e:  # noqa: BLE001 - a catalog read failure must not break warmup
                    self._log.warning(
                        f"Catalog bar load failed for {request.bar_type}: {e}; "
                        "falling back to DNSE API",
                    )
                    bars = []
                if bars:
                    source = "catalog"
                else:
                    self._log.warning(
                        f"No catalog bars for {request.bar_type} within "
                        f"[{start}, {end}]; falling back to DNSE API",
                    )

        if not bars:
            bars = await self._fetch_api_bars(key, start, end)

        self._handle_response(
            BarsResponse(
                self.client_id,
                request.bar_type,
                _with_bar_type(bars, request.bar_type),
                request.request_id,
                self.clock.timestamp_ns(),
                request.start_ns,
                request.end_ns,
                request.params,
            ),
        )
        self._log.info(f"Served {len(bars)} bars from {source} for {request.bar_type}")

    async def _fetch_api_bars(
        self,
        key: SubscriptionKey,
        start: pd.Timestamp | None,
        end: pd.Timestamp | None,
    ) -> list[Bar]:
        """Fetch finished bars from the DNSE REST API; the still-forming bar is left out."""
        query: dict[str, Any] = {
            "symbol": key.symbol,
            "resolution": key.resolution,
        }
        if start is not None:
            query["from"] = int(start.value // SECOND_NS)
        if end is not None:
            query["to"] = int(end.value // SECOND_NS)

        assert self._rest_client is not None
        status, body = await asyncio.to_thread(
            self._rest_client.get_ohlc,
            bar_type=self._config.historical_bar_type,
            query=query,
            dry_run=False,
        )
        if status != 200:
            raise ValueError(
                "DNSE get_ohlc failed with "
                f"status={status}, symbol={query['symbol']}, "
                f"resolution={key.resolution}, body={body}",
            )

        bars = dnse_ohlc_body_to_nautilus_bars(
            body=body,
            symbol=key.symbol,
            resolution=key.resolution,
            venue=self._config.venue,
            price_precision=self._config.price_precision,
            volume_precision=self._config.volume_precision,
            timezone_name=self._config.timezone_name,
            # Weekday rule only: the DNSE working-date list starts today, so it would
            # drop every bar of earlier days.
            working_dates=None,
            drop_invalid_trading_days=self._config.drop_weekend_bars,
        )
        now = self.clock.timestamp_ns()
        return [bar for bar in bars if bar.ts_init <= now]

    async def _ensure_instrument(self, symbol: str) -> object:
        if self.instrument_provider is None:
            raise RuntimeError("The DNSE data client requires an instrument provider")
        instrument_id = InstrumentId(Symbol(symbol), Venue(self._config.venue))
        instrument = self.instrument_provider.find(instrument_id)
        if instrument is None:
            await self.instrument_provider.load_async(instrument_id)
            instrument = self.instrument_provider.find(instrument_id)
        if instrument is None:
            raise ValueError(f"Could not build instrument for symbol={symbol}")
        return instrument

    def _publish_all_instruments(self, venue: Venue | None = None) -> None:
        if self.instrument_provider is None:
            return
        for instrument in self.instrument_provider.get_all().values():
            if venue is None or instrument.id.venue == venue:
                self._handle_instrument(instrument)

    def _on_ohlc_event(self, ohlc: Ohlc) -> None:
        resolution = normalize_dnse_resolution(ohlc.resolution)
        key = SubscriptionKey(symbol=ohlc.symbol, resolution=resolution)
        if resolution == "1" and key in self._subscribed_keys:
            self._last_minute_bar_received_ns = self.clock.timestamp_ns()
            self._bar_stall_reported = False
        if key in self._recovering_keys:
            self._buffered_ohlc_by_key.setdefault(key, []).append(ohlc)
            return
        bar_type = self._bar_types_by_key.get(key)
        if bar_type is None:
            return

        timestamp = dnse_epoch_to_utc_timestamp(ohlc.time)
        if self._config.drop_weekend_bars and not is_valid_vn_trading_day(
            timestamp,
            self._config.timezone_name,
        ):
            return

        bar = dnse_ohlc_to_nautilus_bar(
            ohlc=ohlc,
            venue=self._config.venue,
            price_precision=self._config.price_precision,
            volume_precision=self._config.volume_precision,
            timezone_name=self._config.timezone_name,
        )
        self._publish_bar(key, _with_bar_type([bar], bar_type)[0])

    def _publish_bar(self, key: SubscriptionKey, bar: Bar) -> None:
        last_ts = self._last_bar_ts_by_key.get(key)
        if last_ts is not None and bar.ts_event <= last_ts:
            return
        self._last_bar_ts_by_key[key] = bar.ts_event
        self._handle_data(bar)

    def _on_quote_event(self, quote: Quote) -> None:
        if quote.boardId and quote.boardId != DNSE_MAIN_BOARD:
            return
        symbol = quote.symbol
        if symbol in self._quote_symbols:
            self._handle_data(
                dnse_quote_to_nautilus_quote_tick(
                    quote,
                    venue=self._config.venue,
                    price_precision=self._config.price_precision,
                    volume_precision=self._config.volume_precision,
                    timezone_name=self._config.timezone_name,
                    fallback_ts_ns=self.clock.timestamp_ns(),
                ),
            )
        if symbol in self._book_symbols:
            self._handle_data(
                dnse_quote_to_nautilus_depth10(
                    quote,
                    venue=self._config.venue,
                    price_precision=self._config.price_precision,
                    volume_precision=self._config.volume_precision,
                    timezone_name=self._config.timezone_name,
                    fallback_ts_ns=self.clock.timestamp_ns(),
                ),
            )

    def _on_trade_event(self, trade: Trade) -> None:
        if trade.boardId and trade.boardId != DNSE_MAIN_BOARD:
            return
        if trade.symbol not in self._trade_symbols:
            return
        self._handle_data(
            dnse_trade_to_nautilus_trade_tick(
                trade,
                venue=self._config.venue,
                price_precision=self._config.price_precision,
                volume_precision=self._config.volume_precision,
                timezone_name=self._config.timezone_name,
                fallback_ts_ns=self.clock.timestamp_ns(),
            ),
        )

    def _on_reconnecting(self, info: object) -> None:
        self._log.warning(f"DNSE market-data stream disconnected; reconnecting: {info}")

    def _on_stream_lost(self, attempts: object) -> None:
        self._schedule_stream_check(f"gave up after {attempts} reconnect attempts")

    def _on_stream_error(self, error: object) -> None:
        self._schedule_stream_check(str(error))

    def _schedule_stream_check(self, reason: str) -> None:
        if self._closing:
            return
        self.create_task(self._check_stream_alive(reason), name="dnse_stream_check")

    async def _check_stream_alive(self, reason: str) -> None:
        """Report ERROR only when the DNSE SDK receive loop has stopped, WARNING otherwise."""
        await asyncio.sleep(STREAM_CHECK_DELAY_SECONDS)
        if self._closing:
            return
        # Private attribute of the installed DNSE SDK: the task running its receive loop,
        # which also performs the reconnects. It ends only when the SDK stops receiving.
        receive_task = getattr(self._trading_client, "_message_handler_task", _MISSING)
        if receive_task is _MISSING:
            self._log.warning(
                f"DNSE market-data stream error ({reason}); the DNSE SDK exposes no receive "
                "task, so only the bar watchdog can detect a stopped stream",
            )
            return
        if receive_task is None or receive_task.done():
            if not self._stream_stop_reported:
                self._stream_stop_reported = True
                self._log.error(
                    f"DNSE market-data stream stopped ({reason}); no bars, quotes or trades "
                    "arrive until the node is restarted",
                )
            return
        self._log.warning(f"DNSE market-data stream error ({reason}); the DNSE SDK is reconnecting")

    async def _run_bar_watchdog(self) -> None:
        while not self._closing:
            await asyncio.sleep(BAR_WATCHDOG_INTERVAL_SECONDS)
            await self._check_bar_watchdog(self.clock.timestamp_ns())

    async def _check_bar_watchdog(self, now_ns: int) -> None:
        """Log an ERROR when one-minute bars stop arriving during a continuous session."""
        if self._bar_stall_reported:
            return
        minute_keys = sorted(
            (key for key in self._subscribed_keys if key.resolution == "1"),
            key=lambda key: key.symbol,
        )
        if not minute_keys:
            return
        now = pd.Timestamp(now_ns, tz="UTC").tz_convert(self._config.timezone_name)
        if now.date().isoformat() == self._market_closed_date:
            return
        if self._config.use_dnse_working_dates and not self._market_working_dates:
            try:
                self._market_working_dates = await self._load_market_working_dates()
                self._log.info("DNSE working dates loaded")
            except Exception:  # noqa: BLE001 - still unavailable; checked below via REST bars.
                pass
        if not is_valid_vn_trading_day(
            now.tz_convert("UTC"),
            self._config.timezone_name,
            self._market_working_dates,
        ):
            return
        session_start = next(
            (start for start, end in CONTINUOUS_SESSIONS_LOCAL if start <= now.time() < end),
            None,
        )
        if session_start is None:
            return
        session_start_ns = pd.Timestamp.combine(now.date(), session_start).tz_localize(
            self._config.timezone_name,
        ).value
        last_ns = max(self._last_minute_bar_received_ns or 0, session_start_ns)
        if now_ns - last_ns < BAR_WATCHDOG_MINUTES * 60 * SECOND_NS:
            return
        if not self._market_working_dates:
            # Without the working-date list a weekday holiday also has no bars; the REST
            # API tells the two apart when it still answers.
            has_bars_today = await self._rest_has_bars_on(minute_keys[0], now, now_ns)
            if has_bars_today is False:
                self._market_closed_date = now.date().isoformat()
                self._log.warning(
                    f"No DNSE bar today ({now.date()}) from the stream or the REST API; "
                    "treating the market as closed for the day",
                )
                return
        self._bar_stall_reported = True
        since = pd.Timestamp(last_ns, tz="UTC").tz_convert(self._config.timezone_name)
        self._log.error(
            f"No DNSE one-minute bar since {since:%H:%M:%S} local time "
            f"({BAR_WATCHDOG_MINUTES} minutes) during the continuous session",
        )

    async def _rest_has_bars_on(
        self,
        key: SubscriptionKey,
        now: pd.Timestamp,
        now_ns: int,
    ) -> bool | None:
        """Whether the REST API has one-minute bars for the local day of ``now``; None on failure."""
        day_start = now.normalize()
        try:
            bars = await self._fetch_api_bars(key, day_start.tz_convert("UTC"), now.tz_convert("UTC"))
        except Exception:  # noqa: BLE001 - an unreachable REST API cannot confirm a closed market.
            return None
        return any(day_start.value <= bar.ts_event <= now_ns for bar in bars)

    def _on_reconnected(self, _: object) -> None:
        self._log.info("DNSE market-data stream reconnected; recovering missed bars")
        for key in self._subscribed_keys:
            if key in self._recovering_keys or key not in self._bar_types_by_key:
                continue
            self._recovering_keys.add(key)
            self._buffered_ohlc_by_key[key] = []
            self.create_task(
                self._recover_bars(key),
                name=f"dnse_recover_bars: {key.symbol} {key.resolution}",
            )

    async def _recover_bars(self, key: SubscriptionKey) -> None:
        """Publish the bars that closed while the stream was down, then resume live bars."""
        try:
            last_ts = self._last_bar_ts_by_key.get(key)
            bar_type = self._bar_types_by_key.get(key)
            if last_ts is None or bar_type is None:
                return
            delays = (*BAR_RECOVERY_RETRY_DELAYS_SECONDS, None)
            for attempt, delay in enumerate(delays, start=1):
                try:
                    missed = await self._fetch_api_bars(
                        key,
                        pd.Timestamp(last_ts, tz="UTC"),
                        pd.Timestamp(self.clock.timestamp_ns(), tz="UTC"),
                    )
                except Exception as e:  # noqa: BLE001 - retried, then reported below.
                    if delay is None:
                        since = pd.Timestamp(last_ts, tz="UTC").tz_convert(self._config.timezone_name)
                        self._log.error(
                            f"Could not recover {key.symbol} {key.resolution} bars missed since "
                            f"{since:%Y-%m-%d %H:%M} local time after {attempt} attempts: {e}",
                        )
                        return
                    self._log.warning(
                        f"Bar recovery attempt {attempt} for {key.symbol} {key.resolution} "
                        f"failed: {e}; retrying in {delay:.0f}s",
                    )
                    await asyncio.sleep(delay)
                    continue
                for bar in _with_bar_type(missed, bar_type):
                    self._publish_bar(key, bar)
                return
        finally:
            self._recovering_keys.discard(key)
            for ohlc in self._buffered_ohlc_by_key.pop(key, []):
                self._on_ohlc_event(ohlc)

    async def _load_market_working_dates(self) -> tuple[str, ...]:
        assert self._rest_client is not None
        status, body = await asyncio.to_thread(
            self._rest_client.get_working_dates,
            dry_run=False,
        )
        if status != 200:
            raise ValueError(
                f"DNSE get_working_dates failed with status={status}, body={body}"
            )

        return parse_working_dates_body(body)

    @property
    def _channel_suffix(self) -> str:
        return "msgpack" if self._config.ws_encoding == "msgpack" else "json"

    async def _ensure_quote_stream(self, symbol: str) -> None:
        if symbol in self._quote_stream_symbols:
            return
        if self._trading_client is None:
            raise RuntimeError("DNSE data client is not connected")
        await self._trading_client.subscribe_quotes(
            symbols=sorted(self._quote_stream_symbols | {symbol}),
            encoding=self._config.ws_encoding,
            board_id=DNSE_MAIN_BOARD,
        )
        self._quote_stream_symbols.add(symbol)

    async def _drop_quote_stream_if_unused(self, symbol: str) -> None:
        if symbol in self._quote_symbols or symbol in self._book_symbols:
            return
        if self._trading_client is None:
            raise RuntimeError("DNSE data client is not connected")
        await self._trading_client.unsubscribe(
            f"top_price.{DNSE_MAIN_BOARD}.{self._channel_suffix}",
            [symbol],
        )
        self._quote_stream_symbols.discard(symbol)

    async def _subscribe_quotes(self, command) -> None:
        symbol = command.instrument_id.symbol.value
        if symbol in self._quote_symbols:
            return
        # Registered before subscribing so a quote delivered during the call is kept.
        self._quote_symbols.add(symbol)
        try:
            await self._ensure_quote_stream(symbol)
        except Exception:
            self._quote_symbols.discard(symbol)
            raise

    async def _subscribe_book_deltas(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _subscribe_book_depth(self, command) -> None:
        symbol = command.instrument_id.symbol.value
        if symbol in self._book_symbols:
            return
        self._book_symbols.add(symbol)
        try:
            await self._ensure_quote_stream(symbol)
        except Exception:
            self._book_symbols.discard(symbol)
            raise

    async def _subscribe_mark_prices(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _subscribe_index_prices(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _subscribe_funding_rates(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _subscribe_instrument_status(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _subscribe_instrument_close(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _subscribe_option_greeks(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _unsubscribe_quotes(self, command) -> None:
        symbol = command.instrument_id.symbol.value
        if symbol not in self._quote_symbols:
            return
        self._quote_symbols.discard(symbol)
        await self._drop_quote_stream_if_unused(symbol)

    async def _unsubscribe_book_deltas(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _unsubscribe_book_depth(self, command) -> None:
        symbol = command.instrument_id.symbol.value
        if symbol not in self._book_symbols:
            return
        self._book_symbols.discard(symbol)
        await self._drop_quote_stream_if_unused(symbol)

    async def _unsubscribe_mark_prices(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _unsubscribe_index_prices(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _unsubscribe_funding_rates(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _unsubscribe_instrument_status(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _unsubscribe_instrument_close(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _unsubscribe_option_greeks(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _subscribe_trades(self, command) -> None:
        symbol = command.instrument_id.symbol.value
        if symbol in self._trade_symbols:
            return
        if self._trading_client is None:
            raise RuntimeError("DNSE data client is not connected")
        self._trade_symbols.add(symbol)
        try:
            await self._trading_client.subscribe_trades(
                symbols=sorted(self._trade_symbols),
                encoding=self._config.ws_encoding,
                board_id=DNSE_MAIN_BOARD,
            )
        except Exception:
            self._trade_symbols.discard(symbol)
            raise

    async def _unsubscribe_trades(self, command) -> None:
        symbol = command.instrument_id.symbol.value
        if symbol not in self._trade_symbols:
            return
        if self._trading_client is None:
            raise RuntimeError("DNSE data client is not connected")
        await self._trading_client.unsubscribe(
            f"tick.{DNSE_MAIN_BOARD}.{self._channel_suffix}",
            [symbol],
        )
        self._trade_symbols.discard(symbol)

    async def _request_quotes(self, request) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _request_trades(self, request) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _request_funding_rates(self, request) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _request_book_snapshot(self, request) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _request_book_depth(self, request) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _request_book_deltas(self, request) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _request_option_chain_reference_price(self, request) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)
