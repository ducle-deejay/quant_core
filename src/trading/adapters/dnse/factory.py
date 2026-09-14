from __future__ import annotations

from nautilus_trader.common import Clock
from nautilus_trader.live import ClientCache, DataClientConfig
from nautilus_trader.live.clients import DataClientFactory

from trading.adapters.dnse.config import DnseDataClientConfig
from trading.adapters.dnse.data import DnseLiveDataClient
from trading.adapters.dnse.instruments import DnseInstrumentProvider


class DnseLiveDataClientFactory(DataClientFactory):
    """Nautilus extension factory constructing the DNSE live data client."""

    @staticmethod
    def create(
        *,
        name: str,
        config: DataClientConfig,
        cache: ClientCache,
        clock: Clock,
    ) -> DnseLiveDataClient:
        if not isinstance(config, DnseDataClientConfig):
            raise TypeError("Expected DnseDataClientConfig")
        provider = DnseInstrumentProvider(config=config)
        return DnseLiveDataClient(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            venue=config.venue,
            instrument_provider=provider,
        )
