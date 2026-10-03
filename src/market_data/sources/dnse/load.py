from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import FuturesContract
from nautilus_trader.model import PerpetualContract
from nautilus_trader.persistence import ParquetDataCatalog

from market_data.sources.dnse.quality import validate_transformed_batch
from market_data.sources.dnse.transform import LOCAL_TIMEZONE


REQUIRED_CATALOG_TYPES = {"bars", "instruments", "order_book_depths", "trades"}
# Data type names ParquetDataCatalog.delete_data_range accepts; depth is not its directory name
DELETE_TYPE_NAMES = {"Bar": "bars", "TradeTick": "trades", "OrderBookDepth10": "order_book_depth10"}


def load_day(
    *,
    catalog_path: str | Path,
    transformed: Iterable[list[Any]],
) -> dict[str, int]:
    """Load transformed DNSE batches through the Nautilus catalog public API."""
    catalog = ParquetDataCatalog(str(catalog_path))
    counts: Counter[str] = Counter()
    cleared: set[tuple[str, str]] = set()
    for batch in transformed:
        validate_transformed_batch(batch)
        if isinstance(batch[0], (FuturesContract, PerpetualContract)):
            existing_by_id: dict[str, list[Any]] = {}
            for instrument in catalog.instruments(
                instrument_ids=[instrument.id.value for instrument in batch],
            ):
                existing_by_id.setdefault(instrument.id.value, []).append(instrument)
            batch = [
                instrument
                for instrument in batch
                if not any(
                    _instrument_definition(existing)
                    == _instrument_definition(instrument)
                    for existing in existing_by_id.get(instrument.id.value, [])
                )
            ]
            if not batch:
                continue
            catalog.write_instruments(batch)
            for instrument in batch:
                counts[type(instrument).__name__] += 1
            continue
        type_name = type(batch[0]).__name__
        writer = {
            "Bar": catalog.write_bars,
            "TradeTick": catalog.write_trade_ticks,
            "OrderBookDepth10": catalog.write_order_book_depths,
        }[type_name]
        # A day is written in several batches; clear what an earlier load of that day
        # left before its first batch, since the catalog rejects rows inside a range it
        # already covers
        key = (DELETE_TYPE_NAMES[type_name], _identifier(batch[0]))
        if key not in cleared:
            catalog.delete_data_range(*key, *_local_day_bounds(batch[0].ts_init))
            cleared.add(key)
        writer(batch)
        counts[type(batch[0]).__name__] += len(batch)

    available = set(catalog.list_data_types())
    missing = REQUIRED_CATALOG_TYPES - available
    if missing:
        raise ValueError(f"Nautilus catalog is missing required data types: {sorted(missing)}")
    return dict(counts)


def _instrument_definition(instrument: Any) -> dict[str, Any]:
    definition = dict(instrument.to_dict())
    definition.pop("ts_event", None)
    definition.pop("ts_init", None)
    return definition


def _identifier(record: Any) -> str:
    return str(record.bar_type) if hasattr(record, "bar_type") else str(record.instrument_id)


def _local_day_bounds(ts_init: int) -> tuple[int, int]:
    start = pd.Timestamp(ts_init, tz="UTC").tz_convert(LOCAL_TIMEZONE).normalize()
    return start.value, (start + pd.Timedelta(days=1)).value - 1
