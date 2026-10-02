from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from typing import Any

from nautilus_trader.common import Clock
from nautilus_trader.live import InstrumentProviderConfig
from nautilus_trader.live.providers import InstrumentProvider
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import Symbol

from nautilus_bridge.instruments.derivatives.futures.vn30f1m import (
    CONTINUOUS_SYMBOL,
    VENUE,
    VN30F1M_SESSIONS,
    build_continuous_futures_contract,
    build_monthly_futures_contract,
)

from .config import DnseDataClientConfig
from .api.contracts import UNKNOWN_ACTIVATION
from .api.contracts import VN_TZINFO
from .api.contracts import EntradeMonthlyContract, resolve_active_contract
from .api.entrade_api import EntradeClient


class DnseInstrumentProvider(InstrumentProvider):
    def __init__(self, config: DnseDataClientConfig, clock: Clock | None = None) -> None:
        provider_config = config.instrument_provider or InstrumentProviderConfig(
            load_all=True,
        )
        super().__init__(provider_config)
        self._client_config = config
        self._clock = clock
        self._client: Any | None = None

    def set_client(self, client: Any) -> None:
        """Bind the DNSE REST client when the owning data client connects."""
        self._client = client

    async def load_all_async(self, filters: dict | None = None) -> None:
        for symbol in self._client_config.resolved_symbols:
            self.add(self._build_instrument(symbol))
        if self._client is not None:
            for contract in await self._load_monthly_contracts():
                self.add(contract)

    async def _load_monthly_contracts(self) -> list[object]:
        assert self._client is not None
        instruments = await self._get_json(
            self._client.get_instruments,
            market_id="DVX",
            security_group_id="FU",
            limit=100,
        )
        symbols = [
            str(record["symbol"])
            for record in instruments.get("data", [])
            if str(record.get("symbolType", "")).startswith("VN30F")
        ]
        contracts = []
        for symbol in symbols:
            definition = await self._get_json(
                self._client.get_security_definition,
                symbol,
                board_id="G1",
            )
            final_trade_date = date.fromisoformat(definition[0]["finalTradeDate"][:10])
            expiration = datetime.combine(
                final_trade_date,
                VN30F1M_SESSIONS.closing_auction,
                tzinfo=VN_TZINFO,
            ).astimezone(UTC)
            contracts.append(
                build_monthly_futures_contract(
                    symbol,
                    activation=UNKNOWN_ACTIVATION.isoformat(),
                    expiration=expiration.isoformat(),
                    ts_event=self._load_ts(),
                    ts_init=self._load_ts(),
                ),
            )
        return contracts

    @staticmethod
    async def _get_json(method: Any, *args: object, **kwargs: object) -> Any:
        status, body = await asyncio.to_thread(method, *args, **kwargs)
        if status != 200:
            raise ValueError(f"DNSE {method.__name__} failed with status={status}, body={body}")
        return json.loads(body)

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        for instrument_id in instrument_ids:
            if instrument_id.venue != VENUE:
                continue
            self.add(self._build_instrument(instrument_id.symbol.value))

    def _build_instrument(self, symbol: str) -> object:
        return build_continuous_futures_contract(
            symbol,
            ts_event=self._load_ts(),
            ts_init=self._load_ts(),
        )

    def _load_ts(self) -> int | None:
        return self._clock.timestamp_ns() if self._clock is not None else None


class EntradeInstrumentProvider(InstrumentProvider):
    def __init__(
        self,
        client: EntradeClient | None,
        config: InstrumentProviderConfig | None = None,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(config=config or InstrumentProviderConfig(load_all=True))
        self._client = client
        self._clock = clock
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
        self.add(
            build_continuous_futures_contract(
                ts_event=self._load_ts(),
                ts_init=self._load_ts(),
            ),
        )
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
            self.add(
                contract.to_nautilus_instrument(
                    ts_event=self._load_ts(),
                    ts_init=self._load_ts(),
                ),
            )

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        if any(instrument_id.venue == VENUE for instrument_id in instrument_ids):
            await self.load_all_async(filters)

    def resolve_active_contract(
        self,
        at: datetime | None = None,
    ) -> EntradeMonthlyContract:
        if not self._derivatives:
            raise RuntimeError("Entrade derivatives have not been loaded")
        return resolve_active_contract(
            self._derivatives,
            logical_symbol=CONTINUOUS_SYMBOL.value,
            at=at or datetime.now(UTC),
        )

    def resolve_active_instrument(self, at: datetime | None = None) -> object:
        contract = self.resolve_active_contract(at)
        instrument = self.find(InstrumentId(Symbol(contract.symbol), VENUE))
        if instrument is None:
            raise RuntimeError(
                f"Entrade contract was not loaded into Nautilus: {contract.symbol}"
            )
        return instrument

    def contract_for_instrument(
        self,
        instrument_id: InstrumentId,
    ) -> EntradeMonthlyContract | None:
        if instrument_id.venue != VENUE:
            return None
        return self._contracts.get(instrument_id.symbol.value)

    def _load_ts(self) -> int | None:
        return self._clock.timestamp_ns() if self._clock is not None else None
