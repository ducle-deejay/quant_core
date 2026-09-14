from __future__ import annotations

from nautilus_trader.common import Clock
from nautilus_trader.live import ClientCache, ExecutionClientConfig
from nautilus_trader.live.clients import ExecutionClientFactory
from nautilus_trader.model import TraderId

from trading.adapters.entrade.config import EntradeExecClientConfig
from trading.adapters.entrade.execution import EntradeExecutionClient
from trading.adapters.entrade.instruments import EntradeInstrumentProvider


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
            instrument_spec=config.instrument_spec,
            config=config.instrument_provider,
        )
        return EntradeExecutionClient(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            trader_id=trader_id,
            instrument_provider=provider,
        )
