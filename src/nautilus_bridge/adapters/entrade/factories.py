from __future__ import annotations

from nautilus_trader.common import Clock
from nautilus_trader.live import ClientCache, DataClientConfig, ExecutionClientConfig
from nautilus_trader.live.clients import DataClientFactory, ExecutionClientFactory
from nautilus_trader.model import TraderId

from .config import DnseDataClientConfig, EntradeExecClientConfig
from .data import DnseLiveDataClient
from .execution import EntradeExecutionClient
from .providers import DnseInstrumentProvider, EntradeInstrumentProvider


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
        provider = DnseInstrumentProvider(config=config, clock=clock)
        return DnseLiveDataClient(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            venue=config.venue,
            instrument_provider=provider,
        )


class EntradeLiveExecClientFactory(ExecutionClientFactory):
    """Nautilus factory composing the Entrade execution adapter."""

    @staticmethod
    def create(
        *,
        name: str,
        config: ExecutionClientConfig,
        cache: ClientCache,
        clock: Clock,
        trader_id: TraderId,
    ) -> EntradeExecutionClient:
        if not isinstance(config, EntradeExecClientConfig):
            raise TypeError("Expected EntradeExecClientConfig")
        provider = EntradeInstrumentProvider(
            client=None,
            config=config.instrument_provider,
            clock=clock,
        )
        return EntradeExecutionClient(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            trader_id=trader_id,
            instrument_provider=provider,
        )
