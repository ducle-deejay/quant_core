from __future__ import annotations

from nautilus_trader.config import LiveDataClientConfig

from trading.instruments import FuturesInstrumentSpec


VN_TZ = "Asia/Ho_Chi_Minh"
DNSE_DATA_CLIENT_NAME = "DNSE"
DNSE_API_VERSION = "2026-07-23"
SUPPORTED_DNSE_RESOLUTIONS = frozenset({"1", "3", "5", "15", "30", "60", "1H", "1D", "1W"})
ALLOWED_HISTORICAL_SOURCES = frozenset({"catalog", "api"})


class DnseDataClientConfig(LiveDataClientConfig, frozen=True, kw_only=True):
    """Nautilus extension configuration for the DNSE live data client."""

    api_key: str
    api_secret: str
    instrument_spec: FuturesInstrumentSpec
    rest_base_url: str = "https://openapi.dnse.com.vn"
    api_version: str = DNSE_API_VERSION
    ws_base_url: str = "wss://ws-openapi.dnse.com.vn"
    ws_encoding: str = "json"
    auto_reconnect: bool = True
    max_retries: int = 10
    heartbeat_interval: float = 25.0
    timeout: float = 60.0
    symbols: tuple[str, ...] = ()
    publish_instruments_on_connect: bool = True
    timezone_name: str = VN_TZ
    drop_weekend_bars: bool = True
    use_dnse_working_dates: bool = False
    market_working_dates: tuple[str, ...] = ()
    historical_bar_type: str = "DERIVATIVE"
    volume_precision: int = 0
    historical_source: str = "catalog"
    catalog_path: str | None = None

    def __post_init__(self) -> None:
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
