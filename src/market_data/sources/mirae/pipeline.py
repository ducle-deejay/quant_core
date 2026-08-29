from __future__ import annotations

from datetime import date
from pathlib import Path

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
    extract_day(
        request_history=request_history,
        active_contract=active_contract,
        raw_root=raw,
        day=day,
        continuous_symbol=continuous_symbol,
    )
    if not raw_day.is_dir():
        raise RuntimeError(f"Mirae produced no retained candlestick data for {day}")

    source_bars = validate_raw_day(raw_day)
    loaded = load_day(
        catalog_path=catalog_path,
        transformed=transform_day(raw_day=raw_day, instrument_config=instrument_config),
    )
    if loaded.get("Bar", 0) + loaded.get("SkippedBar", 0) != source_bars:
        raise ValueError("Mirae raw and candidate-bar counts differ")
    return {
        "catalog": str(catalog_path),
        "raw_days": [raw_day.name],
        "records": loaded,
    }
