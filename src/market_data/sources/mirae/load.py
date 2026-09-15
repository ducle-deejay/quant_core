from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from nautilus_trader.model import FuturesContract
from nautilus_trader.persistence import ParquetDataCatalog

from market_data.sources.mirae.quality import validate_transformed_bars
from market_data.sources.mirae.transform import BAR_TYPE


REQUIRED_CATALOG_TYPES = {"bar", "futures_contract"}


def load_day(
    *,
    catalog_path: str | Path,
    transformed: Iterable[list[Any]],
) -> dict[str, int | list[int]]:
    """Load only catalog-absent Mirae bars, preserving existing DNSE bars.

    The returned counts dict additionally carries ``added_bar_timestamps``
    (sorted ints) so the daily orchestrator can verify that the Mirae
    backfill resolved every DNSE-missing timestamp.
    """
    catalog = ParquetDataCatalog(catalog_path)
    counts: Counter[str] = Counter()
    existing_timestamps: set[int] = set()
    added_timestamps: list[int] = []

    for batch in transformed:
        if isinstance(batch[0], FuturesContract):
            existing_instruments = {
                instrument.id.value
                for instrument in catalog.instruments(
                    instrument_ids=[instrument.id.value for instrument in batch],
                )
            }
            new_instruments = [
                instrument
                for instrument in batch
                if instrument.id.value not in existing_instruments
            ]
            if new_instruments:
                catalog.write_instruments(new_instruments)
                counts["FuturesContract"] += len(new_instruments)
            continue

        validate_transformed_bars(batch)
        existing_timestamps.update(
            bar.ts_event
            for bar in catalog.query_bars(
                identifiers=[BAR_TYPE],
                start=batch[0].ts_event,
                end=batch[-1].ts_event + 1,
            )
        )
        missing = [bar for bar in batch if bar.ts_event not in existing_timestamps]
        counts["SkippedBar"] += len(batch) - len(missing)
        if not missing:
            continue
        catalog.write_bars(missing)
        existing_timestamps.update(bar.ts_event for bar in missing)
        counts["Bar"] += len(missing)
        added_timestamps.extend(bar.ts_event for bar in missing)

    available = set(catalog.list_data_types())
    missing_types = REQUIRED_CATALOG_TYPES - available
    if missing_types:
        raise ValueError(
            f"Nautilus catalog is missing required data types: {sorted(missing_types)}",
        )
    counts["added_bar_timestamps"] = sorted(added_timestamps)
    return dict(counts)
