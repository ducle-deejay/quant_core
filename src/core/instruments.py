"""Instrument reference data, loaded from the bundled JSON definitions."""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass, field
from pathlib import Path

#: Directory holding the instrument definition JSON files.
INSTRUMENT_DEFINITIONS_DIR = (
    Path(__file__).resolve().parents[1] / "market_data" / "instrument_definitions"
)


@dataclass(frozen=True)
class CostModel:
    """Per-side cost model at a reference price.

    The scalar per-side cost bundles fee, half-spread and buffer:
    1.461 + 0.333 + 0.5 bp = 2.294 bp per side at reference price 1,500;
    scalar until the two-part model lands.
    """

    cost_per_side_frac: float = 0.000229  # per-side cost, fraction of notional
    reference_price: float = 1500.0
    source: str = "DEC-006-milestone1"


@dataclass(frozen=True)
class Instrument:
    """Static reference data for one tradable instrument.

    Attributes
    ----------
    symbol : str
        Exchange symbol, e.g. ``"VN30F1M"``.
    venue : str
        Venue code as used in Nautilus instrument ids, e.g. ``"HNX"``.
    multiplier : float
        Contract multiplier in VND per index point (e.g. 100_000.0).
    tick_size : float
        Minimum price increment (e.g. 0.1).
    """

    symbol: str
    venue: str
    multiplier: float
    tick_size: float
    cost: CostModel = field(default_factory=CostModel)

    @classmethod
    def load(cls, symbol: str) -> "Instrument":
        """Load one instrument's definition (cached per symbol).

        Reads ``market_data/instrument_definitions/<symbol>.hnx.json`` and
        maps ``symbol``, ``venue`` (falling back to the file's ``exchange``
        key when ``venue`` is absent), ``tick_size`` and ``multiplier``.
        Access rule: ``core`` is the only code allowed to read those
        definition files; every other package obtains multiplier and tick
        size through this method.

        Parameters
        ----------
        symbol : str
            Exchange symbol, e.g. ``"VN30F1M"`` (case-insensitive).

        Returns
        -------
        Instrument
            The immutable instrument reference data.

        Raises
        ------
        FileNotFoundError
            If no definition file exists for ``symbol``.
        ValueError
            If the definition file is missing required keys.
        """
        return _load_instrument_cached(symbol.lower())


@functools.lru_cache(maxsize=None)
def _load_instrument_cached(symbol_lower: str) -> Instrument:
    """Read and parse one instrument definition file (LRU-cached)."""
    path = INSTRUMENT_DEFINITIONS_DIR / f"{symbol_lower}.hnx.json"
    if not path.exists():
        raise FileNotFoundError(
            f"instrument definition not found at {path};"
            f" available: {sorted(p.name for p in INSTRUMENT_DEFINITIONS_DIR.glob('*.json'))}"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    venue = payload.get("venue") or payload.get("exchange")
    missing = [
        key
        for key in ("symbol", "tick_size", "multiplier")
        if payload.get(key) is None
    ]
    if venue is None:
        missing.append("venue")
    if missing:
        raise ValueError(f"instrument definition {path.name} missing keys: {missing}")
    return Instrument(
        symbol=str(payload["symbol"]),
        venue=str(venue),
        multiplier=float(payload["multiplier"]),
        tick_size=float(payload["tick_size"]),
    )
