from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from nautilus_trader.model import FuturesContract
from nautilus_trader.model import PerpetualContract
from nautilus_trader.persistence import ParquetDataCatalog

from market_data.sources.dnse.quality import validate_transformed_batch


REQUIRED_CATALOG_TYPES = {"bars", "instruments", "order_book_depths", "trades"}


def load_day(
    *,
    catalog_path: str | Path,
    transformed: Iterable[list[Any]],
) -> dict[str, int]:
    """Load transformed DNSE batches through the Nautilus catalog public API."""
    catalog = ParquetDataCatalog(str(catalog_path))
    counts: Counter[str] = Counter()
    for batch in transformed:
        validate_transformed_batch(batch)
        if isinstance(batch[0], (FuturesContract, PerpetualContract)):
            existing = {
                instrument.id.value
                for instrument in catalog.instruments(
                    instrument_ids=[instrument.id.value for instrument in batch],
                )
            }
            batch = [instrument for instrument in batch if instrument.id.value not in existing]
            if not batch:
                continue
            catalog.write_instruments(batch)
            for instrument in batch:
                counts[type(instrument).__name__] += 1
            continue
        writer = {
            "Bar": catalog.write_bars,
            "TradeTick": catalog.write_trade_ticks,
            "OrderBookDepth10": catalog.write_order_book_depths,
        }[type(batch[0]).__name__]
        writer(batch)
        counts[type(batch[0]).__name__] += len(batch)

    available = set(catalog.list_data_types())
    missing = REQUIRED_CATALOG_TYPES - available
    if missing:
        raise ValueError(f"Nautilus catalog is missing required data types: {sorted(missing)}")
    return dict(counts)
