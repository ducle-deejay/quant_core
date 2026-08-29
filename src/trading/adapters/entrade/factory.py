from __future__ import annotations

import asyncio

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import MessageBus
from nautilus_trader.live.factories import LiveExecClientFactory

from trading.adapters.entrade.client import EntradeClient
from trading.adapters.entrade.client import EntradeClientConfig
from trading.adapters.entrade.config import EntradeExecClientConfig
from trading.adapters.entrade.execution import EntradeExecutionClient
from trading.adapters.entrade.instruments import EntradeInstrumentProvider


class EntradeLiveExecClientFactory(LiveExecClientFactory):
    """Nautilus factory composing the Entrade execution adapter."""

    @staticmethod
    def create(
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: EntradeExecClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> EntradeExecutionClient:
        client = EntradeClient(
            EntradeClientConfig(
                environment=config.environment,
                base_url=config.base_url,
                timeout_seconds=config.timeout_seconds,
            ),
        )
        provider = EntradeInstrumentProvider(
            client=client,
            instrument_spec=config.instrument_spec,
            config=config.instrument_provider,
        )
        return EntradeExecutionClient(
            loop=loop,
            client=client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
            name=name,
        )
