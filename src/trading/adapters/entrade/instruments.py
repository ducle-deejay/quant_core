from __future__ import annotations

import asyncio
from datetime import UTC
from datetime import datetime

from nautilus_trader.common.config import InstrumentProviderConfig
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument

from trading.adapters.entrade.client import EntradeClient
from trading.adapters.entrade.contracts import EntradeMonthlyContract
from trading.adapters.entrade.contracts import resolve_active_contract
from trading.instruments import FuturesInstrumentSpec
from trading.instruments import build_continuous_futures_contract


class EntradeInstrumentProvider(InstrumentProvider):
    """Nautilus extension providing Entrade monthly futures instruments."""

    def __init__(
        self,
        client: EntradeClient,
        instrument_spec: FuturesInstrumentSpec,
        config: InstrumentProviderConfig | None = None,
    ) -> None:
        super().__init__(config=config or InstrumentProviderConfig())
        self._client = client
        self._instrument_spec = instrument_spec
        self._derivatives: dict = {}
        self._contracts: dict[str, EntradeMonthlyContract] = {}

    async def load_all_async(self, filters: dict | None = None) -> None:
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

    def resolve_active_instrument(self, at: datetime | None = None) -> Instrument:
        contract = self.resolve_active_contract(at)
        instrument = self.find(self._instrument_spec.with_symbol(contract.symbol).instrument_id())
        if instrument is None:
            raise RuntimeError(f"Entrade contract was not loaded into Nautilus: {contract.symbol}")
        return instrument

    def contract_for_instrument(
        self,
        instrument_id: InstrumentId,
    ) -> EntradeMonthlyContract | None:
        if instrument_id.venue != self._instrument_spec.instrument_id().venue:
            return None
        return self._contracts.get(instrument_id.symbol.value)
