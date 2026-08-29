from __future__ import annotations

import asyncio

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import MessageBus
from nautilus_trader.core.correctness import PyCondition
from nautilus_trader.live.factories import LiveDataClientFactory

from trading.adapters.dnse.config import DnseDataClientConfig
from trading.adapters.dnse.data import DnseLiveDataClient
from trading.adapters.dnse.instruments import DnseInstrumentProvider


class DnseLiveDataClientFactory(LiveDataClientFactory):
    """Nautilus extension factory constructing the DNSE live data client."""

    @staticmethod
    def create(
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: DnseDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> DnseLiveDataClient:
        PyCondition.type(config, DnseDataClientConfig, "config")
        provider = DnseInstrumentProvider(config=config)
        return DnseLiveDataClient(
            loop=loop,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
            name=name,
        )
