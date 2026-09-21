from __future__ import annotations

from pathlib import Path

from nautilus_trader.live.providers import InstrumentProvider
from nautilus_trader.model import InstrumentId

from nautilus_bridge.instruments.instruments import FuturesInstrumentSpec
from nautilus_bridge.instruments.instruments import build_continuous_futures_contract
from nautilus_bridge.instruments.instruments import load_futures_instrument_spec


INSTRUMENT_DEFINITIONS_DIR = Path(__file__).resolve().with_name("instrument_definitions")


class InstrumentDefinitionProvider(InstrumentProvider):
    """Load system-owned definitions through the Nautilus provider contract."""

    async def load_all_async(self, filters: dict | None = None) -> None:
        for path in _definition_paths():
            self._add_spec(load_futures_instrument_spec(path))

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        requested = set(instrument_ids)
        for path in _definition_paths():
            spec = load_futures_instrument_spec(path)
            if spec.instrument_id() in requested:
                self._add_spec(spec)

    def resolve_futures_spec(self, instrument: str) -> FuturesInstrumentSpec:
        """Resolve one practitioner instrument name to its technical definition."""
        matches = [spec for spec in _all_specs() if spec.symbol.casefold() == instrument.casefold()]
        if not matches:
            raise ValueError(f"Unknown instrument: {instrument}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous instrument: {instrument}")
        self._add_spec(matches[0])
        return matches[0]

    def _add_spec(self, spec: FuturesInstrumentSpec) -> None:
        self.add(build_continuous_futures_contract(spec))


def resolve_futures_instrument_spec(instrument: str) -> FuturesInstrumentSpec:
    """Resolve a practitioner instrument name through the market-data provider."""
    return InstrumentDefinitionProvider().resolve_futures_spec(instrument)


def instrument_definition_path(instrument: str) -> Path:
    """Return the packaged definition path used by internal data tooling."""
    matches = [
        path
        for path in _definition_paths()
        if load_futures_instrument_spec(path).symbol.casefold() == instrument.casefold()
    ]
    if not matches:
        raise ValueError(f"Unknown instrument: {instrument}")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous instrument: {instrument}")
    return matches[0]


def _definition_paths() -> list[Path]:
    return sorted(INSTRUMENT_DEFINITIONS_DIR.glob("*.json"))


def _all_specs() -> list[FuturesInstrumentSpec]:
    return [load_futures_instrument_spec(path) for path in _definition_paths()]
