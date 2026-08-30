from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dnse import TradingClient  # type: ignore[attr-defined]
from dnse.websocket.models import Ohlc
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import MessageBus
from nautilus_trader.common.signal import generate_signal_class
from nautilus_trader.data.messages import RequestBars
from nautilus_trader.data.messages import RequestData
from nautilus_trader.data.messages import RequestInstrument
from nautilus_trader.data.messages import RequestInstruments
from nautilus_trader.data.messages import SubscribeBars
from nautilus_trader.data.messages import SubscribeData
from nautilus_trader.data.messages import SubscribeInstrument
from nautilus_trader.data.messages import SubscribeInstruments
from nautilus_trader.data.messages import UnsubscribeBars
from nautilus_trader.data.messages import UnsubscribeData
from nautilus_trader.data.messages import UnsubscribeInstrument
from nautilus_trader.data.messages import UnsubscribeInstruments
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarSpecification
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AggregationSource
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.identifiers import ClientId
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from trading.adapters.dnse.calendar import is_valid_vn_trading_day
from trading.adapters.dnse.calendar import parse_working_dates_body
from trading.adapters.dnse.client import create_dnse_rest_client
from trading.adapters.dnse.config import DNSE_DATA_CLIENT_NAME
from trading.adapters.dnse.config import SUPPORTED_DNSE_RESOLUTIONS
from trading.adapters.dnse.config import VN_TZ
from trading.adapters.dnse.config import DnseDataClientConfig
from trading.adapters.dnse.instruments import DnseInstrumentProvider


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CATALOG_PATH = REPO_ROOT / "data" / "catalog"


LIVE_DATA_RECONNECTED_SIGNAL_NAME = "LiveDataReconnected"
LiveDataReconnectedSignal = generate_signal_class(
    LIVE_DATA_RECONNECTED_SIGNAL_NAME,
    str,
)


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


def dnse_epoch_to_utc_timestamp(value: int | float) -> pd.Timestamp:
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


def dnse_ohlc_to_nautilus_bar(
    ohlc: Ohlc,
    venue: str,
    price_precision: int = 1,
    volume_precision: int = 0,
) -> Bar:
    bar_type = build_bar_type_for_symbol(
        symbol=ohlc.symbol, resolution=ohlc.resolution, venue=venue
    )
    timestamp = dnse_epoch_to_utc_timestamp(ohlc.time)
    ts_event = int(timestamp.value)

    return Bar(
        bar_type,
        Price(ohlc.open, price_precision),
        Price(ohlc.high, price_precision),
        Price(ohlc.low, price_precision),
        Price(ohlc.close, price_precision),
        Quantity(ohlc.volume, volume_precision),
        ts_event,
        ts_event,
    )


def parse_dnse_ohlc_body(body: Any) -> dict[str, list[Any]]:
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict):
        raise ValueError(f"Unexpected DNSE OHLC response type: {type(body)}")

    required_keys = ("t", "o", "h", "l", "c", "v")
    if not all(key in body for key in required_keys):
        raise ValueError(f"Unexpected DNSE OHLC response payload: {body}")
    return body


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

    The catalog stores bars under ``data/bar/{bar_type}`` and filters on
    ``ts_init``; catalog bars carry ``ts_event == ts_init`` at the bar open
    time in UTC, matching the DNSE API conversion path (see
    ``dnse_ohlc_to_nautilus_bar``).
    """
    return catalog.bars(bar_types=[str(bar_type)], start=start, end=end)


@dataclass(frozen=True)
class SubscriptionKey:
    """NOX composition key for a DNSE OHLC subscription."""

    symbol: str
    resolution: str


class DnseLiveDataClient(LiveMarketDataClient):
    """Nautilus extension implementing live and historical DNSE market data."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider: DnseInstrumentProvider,
        config: DnseDataClientConfig,
        name: str | None = None,
        trading_client: TradingClient | None = None,
        rest_client: Any | None = None,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=ClientId(name or DNSE_DATA_CLIENT_NAME),
            venue=Venue(config.venue),
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
            config=config,
        )
        self._config = config
        self._trading_client = trading_client or TradingClient(
            api_key=config.api_key,
            api_secret=config.api_secret,
            base_url=config.ws_base_url,
            encoding=config.ws_encoding,
            auto_reconnect=config.auto_reconnect,
            max_retries=config.max_retries,
            heartbeat_interval=config.heartbeat_interval,
            timeout=config.timeout,
        )
        self._rest_client = rest_client or create_dnse_rest_client(
            api_key=config.api_key,
            api_secret=config.api_secret,
            base_url=config.rest_base_url,
            api_version=config.api_version,
        )
        self._catalog: ParquetDataCatalog | None = None
        if config.historical_source == "catalog":
            catalog_path = Path(config.catalog_path) if config.catalog_path else DEFAULT_CATALOG_PATH
            if not catalog_path.is_absolute():
                catalog_path = REPO_ROOT / catalog_path
            self._catalog = ParquetDataCatalog(str(catalog_path))
        self._bar_types_by_key: dict[SubscriptionKey, BarType] = {}
        self._subscribed_keys: set[SubscriptionKey] = set()
        self._last_bar_ts_by_key: dict[SubscriptionKey, int] = {}
        self._recovering_keys: set[SubscriptionKey] = set()
        self._failed_recovery_keys: set[SubscriptionKey] = set()
        self._buffered_ohlc_by_key: dict[SubscriptionKey, list[Ohlc]] = {}
        self._registered_ohlc_handler = False
        self._registered_reconnect_handler = False
        self._market_working_dates: tuple[str, ...] = config.market_working_dates

    async def _connect(self) -> None:
        await self._instrument_provider.load_all_async()
        if self._config.use_dnse_working_dates and not self._market_working_dates:
            self._market_working_dates = await self._load_market_working_dates()
        if not self._registered_ohlc_handler:
            self._trading_client.on("ohlc_closed", self._on_ohlc_event)
            self._registered_ohlc_handler = True
        if not self._registered_reconnect_handler:
            self._trading_client.on("reconnected", self._on_reconnected)
            self._registered_reconnect_handler = True
        await self._trading_client.connect()

        if self._config.publish_instruments_on_connect:
            self._publish_all_instruments()

    async def _disconnect(self) -> None:
        await self._trading_client.disconnect()

    async def _subscribe(self, command: SubscribeData) -> None:
        raise NotImplementedError("Generic custom-data subscriptions are not supported for DNSE")

    async def _unsubscribe(self, command: UnsubscribeData) -> None:
        raise NotImplementedError("Generic custom-data subscriptions are not supported for DNSE")

    async def _subscribe_instruments(self, command: SubscribeInstruments) -> None:
        self._publish_all_instruments()

    async def _subscribe_instrument(self, command: SubscribeInstrument) -> None:
        instrument = await self._ensure_instrument(command.instrument_id.symbol.value)
        self._handle_data(instrument)

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

        await self._trading_client.subscribe_ohlc_closed(
            symbols=[symbol],
            resolution=resolution,
            on_ohlc=self._on_ohlc_event,
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

    async def _request(self, request: RequestData) -> None:
        raise NotImplementedError("Generic custom-data requests are not supported for DNSE")

    async def _request_instrument(self, request: RequestInstrument) -> None:
        instrument = await self._ensure_instrument(request.instrument_id.symbol.value)
        self._handle_instrument(
            instrument,
            correlation_id=request.id,
            start=request.start,
            end=request.end,
            params=request.params,
        )

    async def _request_instruments(self, request: RequestInstruments) -> None:
        await self._instrument_provider.load_all_async()
        instruments = [
            instrument
            for instrument in self._instrument_provider.get_all().values()
            if instrument.venue == request.venue
        ]
        self._handle_instruments(
            request.venue,
            instruments,
            correlation_id=request.id,
            start=request.start,
            end=request.end,
            params=request.params,
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
            query: dict[str, Any] = {
                "symbol": key.symbol,
                "resolution": resolution,
            }
            if start is not None:
                query["from"] = int(start.timestamp())
            if end is not None:
                query["to"] = int(end.timestamp())

            try:
                status, body = self._rest_client.get_ohlc(
                    bar_type=self._config.historical_bar_type,
                    query=query,
                    dry_run=False,
                )
                if status != 200:
                    raise ValueError(
                        "DNSE get_ohlc failed with "
                        f"status={status}, symbol={query['symbol']}, "
                        f"resolution={resolution}, body={body}",
                    )

                bars = dnse_ohlc_body_to_nautilus_bars(
                    body=body,
                    symbol=query["symbol"],
                    resolution=resolution,
                    venue=self._config.venue,
                    price_precision=self._config.price_precision,
                    volume_precision=self._config.volume_precision,
                    timezone_name=self._config.timezone_name,
                    working_dates=self._market_working_dates,
                    drop_invalid_trading_days=self._config.drop_weekend_bars,
                )
            except Exception:
                if key in self._recovering_keys:
                    self._failed_recovery_keys.add(key)
                    self._buffered_ohlc_by_key.pop(key, None)
                raise

        if bars and bars[0].bar_type != request.bar_type:
            bars = [
                Bar(
                    request.bar_type,
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

        self._handle_bars(
            request.bar_type,
            bars,
            correlation_id=request.id,
            start=request.start,
            end=request.end,
            params=request.params,
        )
        self._log.info(f"Served {len(bars)} bars from {source} for {request.bar_type}")

        if key in self._recovering_keys:
            self._complete_bar_recovery(key, bars)

    async def _ensure_instrument(self, symbol: str) -> Instrument:
        instrument_id = InstrumentId(Symbol(symbol), Venue(self._config.venue))
        instrument = self._instrument_provider.find(instrument_id)
        if instrument is None:
            await self._instrument_provider.load_async(instrument_id)
            instrument = self._instrument_provider.find(instrument_id)
        if instrument is None:
            raise ValueError(f"Could not build instrument for symbol={symbol}")
        return instrument

    def _publish_all_instruments(self) -> None:
        for instrument in self._instrument_provider.get_all().values():
            self._handle_data(instrument)

    def _on_ohlc_event(self, ohlc: Ohlc) -> None:
        resolution = normalize_dnse_resolution(ohlc.resolution)
        key = SubscriptionKey(symbol=ohlc.symbol, resolution=resolution)
        if key in self._failed_recovery_keys:
            return
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
            self._market_working_dates,
        ):
            return

        bar = dnse_ohlc_to_nautilus_bar(
            ohlc=ohlc,
            venue=self._config.venue,
            price_precision=self._config.price_precision,
            volume_precision=self._config.volume_precision,
        )
        if bar.bar_type != bar_type:
            bar = Bar(
                bar_type,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.ts_event,
                bar.ts_init,
            )

        last_ts = self._last_bar_ts_by_key.get(key)
        if last_ts is not None and bar.ts_event <= last_ts:
            return

        self._last_bar_ts_by_key[key] = bar.ts_event
        self._handle_data_py(bar)

    def _on_reconnected(self, _: object) -> None:
        now = self._clock.timestamp_ns()
        for key in self._subscribed_keys:
            bar_type = self._bar_types_by_key.get(key)
            if bar_type is None:
                continue
            self._recovering_keys.add(key)
            self._failed_recovery_keys.discard(key)
            self._buffered_ohlc_by_key[key] = []
            self._handle_data_py(
                LiveDataReconnectedSignal(
                    value=str(bar_type),
                    ts_event=now,
                    ts_init=now,
                ),
            )

    def _complete_bar_recovery(self, key: SubscriptionKey, bars: list[Bar]) -> None:
        if bars:
            self._last_bar_ts_by_key[key] = max(bar.ts_event for bar in bars)
        buffered = self._buffered_ohlc_by_key.pop(key, [])
        self._recovering_keys.discard(key)
        self._failed_recovery_keys.discard(key)
        for ohlc in buffered:
            self._on_ohlc_event(ohlc)

    async def _load_market_working_dates(self) -> tuple[str, ...]:
        status, body = self._rest_client.get_working_dates(dry_run=False)
        if status != 200:
            raise ValueError(f"DNSE get_working_dates failed with status={status}, body={body}")

        return parse_working_dates_body(body)
