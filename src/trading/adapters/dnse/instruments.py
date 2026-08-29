from __future__ import annotations

from nautilus_trader.common.config import InstrumentProviderConfig
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import Instrument

from trading.adapters.dnse.config import DnseDataClientConfig
from trading.instruments import build_continuous_futures_contract


class DnseInstrumentProvider(InstrumentProvider):
    """Nautilus extension providing configured DNSE instruments."""

    def __init__(self, config: DnseDataClientConfig) -> None:
        provider_config = config.instrument_provider or InstrumentProviderConfig()
        super().__init__(provider_config)
        self._client_config = config

    async def load_all_async(self, filters: dict | None = None) -> None:
        for symbol in self._client_config.resolved_symbols:
            self.add(self._build_instrument(symbol))

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        for instrument_id in instrument_ids:
            if instrument_id.venue != Venue(self._client_config.venue):
                continue
            self.add(self._build_instrument(instrument_id.symbol.value))

    def _build_instrument(self, symbol: str) -> Instrument:
        return build_continuous_futures_contract(
            spec=self._client_config.instrument_spec.with_symbol(symbol),
        )
