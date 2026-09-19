from __future__ import annotations

from typing import Any, Self

from nautilus_trader.live import (
    DataClientConfig,
    ExecutionClientConfig,
    InstrumentProviderConfig,
)

from market_data.instruments import FuturesInstrumentSpec

from .constants import ALLOWED_HISTORICAL_SOURCES
from .constants import DNSE_API_VERSION
from .constants import VN_TZ
from .api.entrade_api import EntradeAccount

# The PyO3 base configs materialize a default ``InstrumentProviderConfig``
# with ``load_all=False``, so the default must be normalized while the value
# is forwarded into the base constructor.
DEFAULT_INSTRUMENT_PROVIDER = InstrumentProviderConfig(load_all=True)


class DnseDataClientConfig(DataClientConfig):
    """Nautilus extension configuration for the DNSE live data client."""

    instrument_spec: FuturesInstrumentSpec

    def __new__(
        cls,
        *,
        api_key: str,
        api_secret: str,
        instrument_spec: FuturesInstrumentSpec,
        rest_base_url: str = "https://openapi.dnse.com.vn",
        api_version: str = DNSE_API_VERSION,
        ws_base_url: str = "wss://ws-openapi.dnse.com.vn",
        ws_encoding: str = "json",
        auto_reconnect: bool = True,
        max_retries: int = 10,
        heartbeat_interval: float = 25.0,
        timeout: float = 60.0,
        symbols: tuple[str, ...] = (),
        publish_instruments_on_connect: bool = True,
        timezone_name: str = VN_TZ,
        drop_weekend_bars: bool = True,
        use_dnse_working_dates: bool = False,
        market_working_dates: tuple[str, ...] = (),
        historical_bar_type: str = "DERIVATIVE",
        volume_precision: int = 0,
        historical_source: str = "catalog",
        catalog_path: str | None = None,
        handle_revised_bars: bool | None = None,
        instrument_provider: Any = None,
        routing: Any = None,
        **kwargs: Any,
    ) -> Self:
        del (
            api_key,
            api_secret,
            instrument_spec,
            rest_base_url,
            api_version,
            ws_base_url,
            ws_encoding,
            auto_reconnect,
            max_retries,
            heartbeat_interval,
            timeout,
            symbols,
            publish_instruments_on_connect,
            timezone_name,
            drop_weekend_bars,
            use_dnse_working_dates,
            market_working_dates,
            historical_bar_type,
            volume_precision,
            historical_source,
            catalog_path,
        )
        return DataClientConfig.__new__(
            cls,
            handle_revised_bars=handle_revised_bars,
            instrument_provider=instrument_provider or DEFAULT_INSTRUMENT_PROVIDER,
            routing=routing,
            **kwargs,
        )

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        instrument_spec: FuturesInstrumentSpec,
        rest_base_url: str = "https://openapi.dnse.com.vn",
        api_version: str = DNSE_API_VERSION,
        ws_base_url: str = "wss://ws-openapi.dnse.com.vn",
        ws_encoding: str = "json",
        auto_reconnect: bool = True,
        max_retries: int = 10,
        heartbeat_interval: float = 25.0,
        timeout: float = 60.0,
        symbols: tuple[str, ...] = (),
        publish_instruments_on_connect: bool = True,
        timezone_name: str = VN_TZ,
        drop_weekend_bars: bool = True,
        use_dnse_working_dates: bool = False,
        market_working_dates: tuple[str, ...] = (),
        historical_bar_type: str = "DERIVATIVE",
        volume_precision: int = 0,
        historical_source: str = "catalog",
        catalog_path: str | None = None,
        handle_revised_bars: bool | None = None,
        instrument_provider: Any = None,
        routing: Any = None,
        **kwargs: Any,
    ) -> None:
        del handle_revised_bars, instrument_provider, routing, kwargs
        self.api_key = api_key
        self.api_secret = api_secret
        self.instrument_spec = instrument_spec
        self.rest_base_url = rest_base_url
        self.api_version = api_version
        self.ws_base_url = ws_base_url
        self.ws_encoding = ws_encoding
        self.auto_reconnect = auto_reconnect
        self.max_retries = max_retries
        self.heartbeat_interval = heartbeat_interval
        self.timeout = timeout
        self.symbols = tuple(symbols)
        self.publish_instruments_on_connect = publish_instruments_on_connect
        self.timezone_name = timezone_name
        self.drop_weekend_bars = drop_weekend_bars
        self.use_dnse_working_dates = use_dnse_working_dates
        self.market_working_dates = tuple(market_working_dates)
        self.historical_bar_type = historical_bar_type
        self.volume_precision = volume_precision
        self.historical_source = historical_source
        self.catalog_path = catalog_path
        if self.historical_source not in ALLOWED_HISTORICAL_SOURCES:
            raise ValueError(
                f"Invalid historical_source={self.historical_source!r}; "
                f"expected one of {sorted(ALLOWED_HISTORICAL_SOURCES)}",
            )

    @property
    def venue(self) -> str:
        return self.instrument_spec.venue

    @property
    def price_precision(self) -> int:
        return self.instrument_spec.price_precision

    @property
    def resolved_symbols(self) -> tuple[str, ...]:
        return self.symbols or (self.instrument_spec.symbol,)


class EntradeExecClientConfig(ExecutionClientConfig):
    """
    Nautilus extension configuration for Entrade execution.

    The ``account`` field selects the Entrade account (demo papertrade or
    live real money); it is independent of the Nautilus node ``Environment``
    context, which should be ``Environment.LIVE`` for this client.
    """

    instrument_spec: FuturesInstrumentSpec

    def __new__(
        cls,
        *,
        instrument_spec: FuturesInstrumentSpec,
        username: str | None = None,
        password: str | None = None,
        investor_id: int | str | None = None,
        account_id: str,
        account: EntradeAccount = EntradeAccount.DEMO,
        base_url: str = "https://services.entrade.com.vn",
        timeout_seconds: float = 30.0,
        instrument_provider: Any = None,
        routing: Any = None,
        **kwargs: Any,
    ) -> Self:
        del (
            instrument_spec,
            username,
            password,
            investor_id,
            account_id,
            account,
            base_url,
            timeout_seconds,
        )
        return ExecutionClientConfig.__new__(
            cls,
            instrument_provider=instrument_provider or DEFAULT_INSTRUMENT_PROVIDER,
            routing=routing,
            **kwargs,
        )

    def __init__(
        self,
        *,
        instrument_spec: FuturesInstrumentSpec,
        username: str | None = None,
        password: str | None = None,
        investor_id: int | str | None = None,
        account_id: str,
        account: EntradeAccount = EntradeAccount.DEMO,
        base_url: str = "https://services.entrade.com.vn",
        timeout_seconds: float = 30.0,
        instrument_provider: Any = None,
        routing: Any = None,
        **kwargs: Any,
    ) -> None:
        del instrument_provider, routing, kwargs
        self.instrument_spec = instrument_spec
        self.username = username
        self.password = password
        self.investor_id = investor_id
        self.account_id = account_id
        self.account = EntradeAccount(account)
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
