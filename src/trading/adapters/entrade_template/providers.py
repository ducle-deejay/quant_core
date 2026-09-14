from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from nautilus_trader.live import InstrumentProviderConfig
from nautilus_trader.live.providers import InstrumentProvider
from nautilus_trader.model import InstrumentId, Venue

from trading.instruments import FuturesInstrumentSpec, build_continuous_futures_contract

from .config import DnseDataClientConfig
from .api.contracts import EntradeMonthlyContract, resolve_active_contract
from .api.entrade_api import EntradeClient


class DnseInstrumentProvider(InstrumentProvider):
    """Nautilus extension providing configured DNSE instruments."""

    def __init__(self, config: DnseDataClientConfig) -> None:
        provider_config = config.instrument_provider or InstrumentProviderConfig(
            load_all=True,
        )
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

    def _build_instrument(self, symbol: str) -> object:
        return build_continuous_futures_contract(
            spec=self._client_config.instrument_spec.with_symbol(symbol),
        )


class EntradeInstrumentProvider(InstrumentProvider):
    """Nautilus extension providing Entrade monthly futures instruments."""

    def __init__(
        self,
        client: EntradeClient | None,
        instrument_spec: FuturesInstrumentSpec,
        config: InstrumentProviderConfig | None = None,
    ) -> None:
        super().__init__(config=config or InstrumentProviderConfig(load_all=True))
        self._client = client
        self._instrument_spec = instrument_spec
        self._derivatives: dict = {}
        self._contracts: dict[str, EntradeMonthlyContract] = {}

    @property
    def client(self) -> EntradeClient | None:
        return self._client

    def set_client(self, client: EntradeClient) -> None:
        """Bind the network client when the owning execution client connects."""
        self._client = client

    async def load_all_async(self, filters: dict | None = None) -> None:
        if self._client is None:
            raise RuntimeError("Entrade instrument provider is not connected")
        self._derivatives = await asyncio.to_thread(self._client.list_derivatives)
        self.add(build_continuous_futures_contract(self._instrument_spec))
        records = self._derivatives.get("data", [])
        self._contracts = {
            contract.symbol: contract
            for record in records
            if isinstance(record, dict)
            and record.get("symbol")
            and record.get("expirationDate")
            and str(record.get("type", "")).startswith("VN30F")
            for contract in (EntradeMonthlyContract.from_payload(record),)
        }
        for contract in self._contracts.values():
            self.add(contract.to_nautilus_instrument(self._instrument_spec))

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        venue = self._instrument_spec.instrument_id().venue
        if any(instrument_id.venue == venue for instrument_id in instrument_ids):
            await self.load_all_async(filters)

    def resolve_active_contract(
        self,
        at: datetime | None = None,
    ) -> EntradeMonthlyContract:
        if not self._derivatives:
            raise RuntimeError("Entrade derivatives have not been loaded")
        return resolve_active_contract(
            self._derivatives,
            logical_symbol=self._instrument_spec.symbol,
            at=at or datetime.now(UTC),
        )

    def resolve_active_instrument(self, at: datetime | None = None) -> object:
        contract = self.resolve_active_contract(at)
        instrument = self.find(
            self._instrument_spec.with_symbol(contract.symbol).instrument_id()
        )
        if instrument is None:
            raise RuntimeError(
                f"Entrade contract was not loaded into Nautilus: {contract.symbol}"
            )
        return instrument

    def contract_for_instrument(
        self,
        instrument_id: InstrumentId,
    ) -> EntradeMonthlyContract | None:
        if instrument_id.venue != self._instrument_spec.instrument_id().venue:
            return None
        return self._contracts.get(instrument_id.symbol.value)
