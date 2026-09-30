from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import FuturesContract
from nautilus_trader.model import PerpetualContract
from nautilus_trader.persistence import ParquetDataCatalog

from market_data.sources.mirae.quality import validate_transformed_bars
from market_data.sources.mirae.transform import BAR_TYPE
from market_data.sources.mirae.transform import LOCAL_TIMEZONE


REQUIRED_CATALOG_TYPES = {"bars", "instruments"}
FULL_DAY_BARS = 241


def load_day(
    *,
    catalog_path: str | Path,
    transformed: Iterable[list[Any]],
) -> dict[str, int | list[int]]:
    """Backfill Mirae bars one trading day at a time, keeping DNSE first.

    Per trading day: a complete catalog day is kept; otherwise a complete Mirae
    day replaces it; otherwise Mirae fills only the catalog-absent timestamps.
    A changed day is deleted and rewritten as one file, because a file inserted
    inside an existing file interval (a partial day, or an absent day inside a
    multi-day file) would overlap that interval.

    ``Bar`` counts Mirae bars written and ``SkippedBar`` the rest. The returned
    counts dict additionally carries ``added_bar_timestamps`` (sorted ints) so
    the daily orchestrator can verify that the Mirae backfill resolved every
    DNSE-missing timestamp.
    """
    catalog = ParquetDataCatalog(str(catalog_path))
    counts: Counter[str] = Counter()
    added_timestamps: list[int] = []

    for batch in transformed:
        if isinstance(batch[0], (FuturesContract, PerpetualContract)):
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
                for instrument in new_instruments:
                    counts[type(instrument).__name__] += 1
            continue

        validate_transformed_bars(batch)
        candidate_days = _group_by_trading_day(batch)
        # Catalog queries filter start/end on ts_init (nautilus_trader crates/persistence
        # common/datafusion.rs build_query), so query whole local days
        existing_days = _group_by_trading_day(
            catalog.query_bars(
                identifiers=[BAR_TYPE],
                start=_day_bounds(min(candidate_days))[0],
                end=_day_bounds(max(candidate_days))[1],
            ),
        )
        for day, candidate in sorted(candidate_days.items()):
            existing = existing_days.get(day, {})
            selected = _select_day_bars(existing, candidate)
            from_candidate = [ts for ts in selected if selected[ts] is candidate.get(ts)]
            counts["Bar"] += len(from_candidate)
            counts["SkippedBar"] += len(candidate) - len(from_candidate)
            if not from_candidate:
                continue
            # Also run for an absent day: it splits any file whose interval spans the day
            catalog.delete_data_range("bars", BAR_TYPE, *_day_bounds(day))
            catalog.write_bars([selected[ts] for ts in sorted(selected)])
            added_timestamps.extend(ts for ts in selected if ts not in existing)

    available = set(catalog.list_data_types())
    missing_types = REQUIRED_CATALOG_TYPES - available
    if missing_types:
        raise ValueError(
            f"Nautilus catalog is missing required data types: {sorted(missing_types)}",
        )
    counts["added_bar_timestamps"] = sorted(added_timestamps)
    return dict(counts)


def _select_day_bars(existing: dict[int, Any], candidate: dict[int, Any]) -> dict[int, Any]:
    if len(existing) == FULL_DAY_BARS:
        return existing
    if len(candidate) == FULL_DAY_BARS:
        return candidate
    return {**{ts: bar for ts, bar in candidate.items() if ts not in existing}, **existing}


def _group_by_trading_day(bars: Iterable[Any]) -> dict[date, dict[int, Any]]:
    days: dict[date, dict[int, Any]] = {}
    for bar in bars:
        day = pd.Timestamp(bar.ts_event, tz="UTC").tz_convert(LOCAL_TIMEZONE).date()
        days.setdefault(day, {})[bar.ts_event] = bar
    return days


def _day_bounds(day: date) -> tuple[int, int]:
    """Inclusive nanosecond bounds of one local trading day."""
    start = pd.Timestamp(day, tz=LOCAL_TIMEZONE)
    end = pd.Timestamp(day + timedelta(days=1), tz=LOCAL_TIMEZONE)
    return start.value, end.value - 1
