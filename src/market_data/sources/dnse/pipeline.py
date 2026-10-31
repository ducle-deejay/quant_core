from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path

from market_data.logs import stage
from market_data.sources.dnse.extract import ClientFactory
from market_data.sources.dnse.extract import extract_day
from market_data.sources.dnse.load import load_day
from market_data.sources.dnse.validate import MissingTrades
from market_data.sources.dnse.validate import validate_raw_delivery
from market_data.sources.dnse.transform import transform_day


def run_daily(
    *,
    client_factory: ClientFactory,
    raw_root: str | Path,
    catalog_path: str | Path,
    continuous_symbol: str,
    day: date,
    request_delay_seconds: float = 0.02,
) -> dict[str, object]:
    """Run the daily DNSE Extract, Transform, and Load workflow."""
    raw = Path(raw_root)
    catalog = Path(catalog_path)
    extracted = extract_day(
        client_factory=client_factory,
        raw_root=raw,
        day=day,
        continuous_symbol=continuous_symbol,
        request_delay_seconds=request_delay_seconds,
    )

    if (catalog / "data").exists():
        raw_days = [raw / day.isoformat()] if (raw / day.isoformat()).is_dir() else []
    else:
        raw_days = sorted(
            path
            for path in raw.iterdir()
            if path.is_dir() and path.name != "contracts" and date.fromisoformat(path.name) <= day
        )

    counts: Counter[str] = Counter()
    missing_bar_timestamps: list[int] = []
    missing_trades: list[MissingTrades] = []
    for raw_day in raw_days:
        if extracted is not None and raw_day.name == day.isoformat():
            validation = extracted
        else:
            with stage("DNSE", "validate", date.fromisoformat(raw_day.name)):
                validation = validate_raw_delivery(raw_day)

        with stage("DNSE", "load", date.fromisoformat(raw_day.name)) as details:
            loaded = load_day(catalog_path=catalog, transformed=transform_day(raw_day=raw_day))
            _reconcile_counts(validation.counts, loaded)
            details.update(
                bars=loaded.get("Bar", 0),
                trades=loaded.get("TradeTick", 0),
                order_book_rows=loaded.get("OrderBookDepth10", 0),
            )
        counts.update(loaded)
        missing_bar_timestamps.extend(validation.missing_bar_timestamps)
        missing_trades.extend(validation.missing_trades)
    return {
        "catalog": str(catalog),
        "raw_days": [path.name for path in raw_days],
        "records": dict(counts),
        "missing_bar_timestamps": missing_bar_timestamps,
        "missing_trades": [asdict(missing) for missing in missing_trades],
    }


def _reconcile_counts(expected: dict[str, int], loaded: dict[str, int]) -> None:
    observed = {
        "bars": loaded.get("Bar", 0),
        "trades": loaded.get("TradeTick", 0),
        "orderbook": loaded.get("OrderBookDepth10", 0),
    }
    if observed != expected:
        raise ValueError(f"DNSE raw and catalog record counts differ: {expected} != {observed}")
