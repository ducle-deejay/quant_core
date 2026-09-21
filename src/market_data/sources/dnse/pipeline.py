from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from market_data.sources import ETLStageError
from market_data.sources.dnse.extract import ClientFactory
from market_data.sources.dnse.extract import extract_day
from market_data.sources.dnse.load import load_day
from market_data.sources.dnse.quality import validate_raw_delivery
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
    try:
        extract_day(
            client_factory=client_factory,
            raw_root=raw,
            day=day,
            continuous_symbol=continuous_symbol,
            request_delay_seconds=request_delay_seconds,
        )
    except Exception as error:
        raise ETLStageError(source="DNSE", stage="extract", cause=error) from error

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
    for raw_day in raw_days:
        try:
            validation = validate_raw_delivery(raw_day)
        except Exception as error:
            raise ETLStageError(source="DNSE", stage="extract", cause=error) from error

        def transformed(current_raw_day: Path = raw_day) -> Iterator[list[Any]]:
            try:
                yield from transform_day(
                    raw_day=current_raw_day,
                )
            except ETLStageError:
                raise
            except Exception as error:
                raise ETLStageError(source="DNSE", stage="transform", cause=error) from error

        try:
            loaded = load_day(
                catalog_path=catalog,
                transformed=transformed(),
            )
            _reconcile_counts(validation.counts, loaded)
        except ETLStageError:
            raise
        except Exception as error:
            raise ETLStageError(source="DNSE", stage="load", cause=error) from error
        counts.update(loaded)
        missing_bar_timestamps.extend(validation.missing_bar_timestamps)
    return {
        "catalog": str(catalog),
        "raw_days": [path.name for path in raw_days],
        "records": dict(counts),
        "missing_bar_timestamps": missing_bar_timestamps,
    }


def retained_contract_symbol(raw_root: str | Path, day: date) -> str | None:
    trades = Path(raw_root) / day.isoformat() / "hnx" / "futures" / "trades"
    if not trades.is_dir():
        return None
    symbols = sorted(path.name for path in trades.iterdir() if path.is_dir())
    if len(symbols) > 1:
        raise ValueError(f"Expected at most one retained DNSE contract for {day}: {symbols}")
    return symbols[0] if symbols else None


def _reconcile_counts(expected: dict[str, int], loaded: dict[str, int]) -> None:
    observed = {
        "bars": loaded.get("Bar", 0),
        "trades": loaded.get("TradeTick", 0),
        "orderbook": loaded.get("OrderBookDepth10", 0),
    }
    if observed != expected:
        raise ValueError(f"DNSE raw and catalog record counts differ: {expected} != {observed}")
