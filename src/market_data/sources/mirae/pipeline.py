from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from market_data.sources import ETLStageError
from market_data.sources.mirae.extract import HistoryRequest
from market_data.sources.mirae.extract import extract_day
from market_data.sources.mirae.load import load_day
from market_data.sources.mirae.quality import validate_raw_day
from market_data.sources.mirae.transform import transform_day


def run_daily(
    *,
    request_history: HistoryRequest,
    active_contract: str | None,
    raw_root: str | Path,
    catalog_path: str | Path,
    instrument_config: str | Path,
    continuous_symbol: str,
    day: date,
) -> dict[str, object]:
    """Run the Mirae candlestick Extract, Transform, and DNSE-first Load workflow."""
    raw = Path(raw_root)
    raw_day = raw / day.isoformat()
    try:
        extract_day(
            request_history=request_history,
            active_contract=active_contract,
            raw_root=raw,
            day=day,
            continuous_symbol=continuous_symbol,
        )
    except Exception as error:
        raise ETLStageError(source="Mirae", stage="extract", cause=error) from error
    if not raw_day.is_dir():
        raise ETLStageError(
            source="Mirae",
            stage="extract",
            cause=RuntimeError(f"Mirae produced no retained candlestick data for {day}"),
        )

    try:
        source_bars = validate_raw_day(raw_day)
    except Exception as error:
        raise ETLStageError(source="Mirae", stage="extract", cause=error) from error

    def transformed() -> Iterator[list[Any]]:
        try:
            yield from transform_day(raw_day=raw_day, instrument_config=instrument_config)
        except ETLStageError:
            raise
        except Exception as error:
            raise ETLStageError(source="Mirae", stage="transform", cause=error) from error

    try:
        loaded = load_day(
            catalog_path=catalog_path,
            transformed=transformed(),
        )
    except ETLStageError:
        raise
    except Exception as error:
        raise ETLStageError(source="Mirae", stage="load", cause=error) from error
    if loaded.get("Bar", 0) + loaded.get("SkippedBar", 0) != source_bars:
        raise ETLStageError(
            source="Mirae",
            stage="load",
            cause=ValueError("Mirae raw and candidate-bar counts differ"),
        )
    return {
        "catalog": str(catalog_path),
        "raw_days": [raw_day.name],
        "records": loaded,
    }
