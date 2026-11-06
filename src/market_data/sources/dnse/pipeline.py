from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import Bar

from market_data import LOCAL_TIMEZONE
from market_data.clean import FIELDS
from market_data.clean import CleanResult
from market_data.clean import clean_day
from market_data.clean import summary_gaps
from market_data.clean import day_summary
from market_data.logs import fields
from market_data.logs import stage
from market_data.sources.dnse.extract import ClientFactory
from market_data.sources.dnse.extract import extract_day
from market_data.sources.dnse.load import load_day
from market_data.sources.dnse.validate import MissingTrades
from market_data.sources.dnse.validate import validate_raw_delivery
from market_data.sources.dnse.transform import _bar_ts_init
from market_data.sources.dnse.transform import transform_day


def run_daily(
    *,
    client_factory: ClientFactory,
    raw_root: str | Path,
    catalog_path: str | Path,
    continuous_symbol: str,
    day: date,
    broker_bars: list[pd.DataFrame] | None = None,
    request_delay_seconds: float = 0.02,
) -> dict[str, object]:
    """Run the daily DNSE Extract, Transform, Clean and Load workflow; ``day``'s bars are cleaned when ``broker_bars`` is given."""
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
    cleaned: CleanResult | None = None
    for raw_day in raw_days:
        if extracted is not None and raw_day.name == day.isoformat():
            validation = extracted
        else:
            with stage("DNSE", "validate", date.fromisoformat(raw_day.name)):
                validation = validate_raw_delivery(raw_day)

        transformed = transform_day(raw_day=raw_day)
        results: list[CleanResult] = []
        if broker_bars is not None and raw_day.name == day.isoformat():
            transformed = _cleaned(transformed, broker_bars, day, results)
        with stage("DNSE", "load", date.fromisoformat(raw_day.name)) as details:
            loaded = load_day(catalog_path=catalog, transformed=transformed)
            expected = dict(validation.counts)
            missing = list(validation.missing_bar_timestamps)
            if results:
                cleaned = results[0]
                expected["bars"] += len(cleaned.filled)
                filled = {int(timestamp.timestamp()) for timestamp in cleaned.filled}
                missing = [timestamp for timestamp in missing if timestamp not in filled]
            _reconcile_counts(expected, loaded)
            details.update(
                bars=loaded.get("Bar", 0),
                trades=loaded.get("TradeTick", 0),
                order_book_rows=loaded.get("OrderBookDepth10", 0),
            )
        counts.update(loaded)
        missing_bar_timestamps.extend(missing)
        missing_trades.extend(validation.missing_trades)
    return {
        "catalog": str(catalog),
        "raw_days": [path.name for path in raw_days],
        "records": dict(counts),
        "missing_bar_timestamps": missing_bar_timestamps,
        "missing_trades": [asdict(missing) for missing in missing_trades],
        "clean": None if cleaned is None else {
            "outcome": cleaned.outcome,
            "filled": [_local_minute(timestamp) for timestamp in cleaned.filled],
            "corrected": [_local_minute(timestamp) for timestamp in cleaned.corrected],
            "reason": cleaned.reason,
            "dnse": day_summary(cleaned.bars) if not cleaned.bars.empty else None,
            "broker_summary": cleaned.broker_summary,
            "gaps": summary_gaps(day_summary(cleaned.bars), cleaned.broker_summary) if not cleaned.bars.empty else {},
        },
    }


def _cleaned(
    transformed: Iterator[list[Any]],
    broker_bars: list[pd.DataFrame],
    day: date,
    results: list[CleanResult],
) -> Iterator[list[Any]]:
    """The transformed batches with the bar batch cleaned; its CleanResult is appended to ``results``."""
    continuous = None
    for batch in transformed:
        if continuous is None:
            continuous = batch[0]
        if batch and isinstance(batch[0], Bar):
            result = _clean_bars(batch, broker_bars, day)
            results.append(result)
            batch = [
                Bar(
                    batch[0].bar_type,
                    continuous.make_price(row.open),
                    continuous.make_price(row.high),
                    continuous.make_price(row.low),
                    continuous.make_price(row.close),
                    continuous.make_qty(row.volume),
                    int(row.timestamp.value),
                    _bar_ts_init(row.timestamp, int(row.timestamp.value)),
                )
                for row in result.bars.itertuples(index=False)
            ]
        yield batch


def _clean_bars(bars: list[Bar], broker_bars: list[pd.DataFrame], day: date) -> CleanResult:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([bar.ts_event for bar in bars], unit="ns", utc=True),
            "open": [bar.open.as_double() for bar in bars],
            "high": [bar.high.as_double() for bar in bars],
            "low": [bar.low.as_double() for bar in bars],
            "close": [bar.close.as_double() for bar in bars],
            "volume": [bar.volume.as_double() for bar in bars],
        },
    )
    with stage("DNSE", "clean", day) as details:
        result = clean_day(frame, broker_bars)
        log = logging.getLogger("DNSE.clean")
        before = frame.set_index("timestamp")
        after = result.bars.set_index("timestamp")
        for timestamp in result.filled:
            values = {name: _value(name, after.at[timestamp, name]) for name in FIELDS}
            log.info("bar filled %s", fields(day=day, minute=_local_minute(timestamp), **values))
        for timestamp in result.corrected:
            changes = {
                name: f"{_value(name, before.at[timestamp, name])}->{_value(name, after.at[timestamp, name])}"
                for name in FIELDS
                if before.at[timestamp, name] != after.at[timestamp, name]
            }
            log.info("bar corrected %s", fields(day=day, minute=_local_minute(timestamp), **changes))
        details.update(outcome=result.outcome, filled=len(result.filled), corrected=len(result.corrected))
        if result.reason:
            details["reason"] = result.reason
    return result


def _value(name: str, value: float) -> int | float:
    return int(value) if name == "volume" else float(value)


def _local_minute(timestamp: pd.Timestamp) -> str:
    return pd.Timestamp(timestamp).tz_convert(LOCAL_TIMEZONE).strftime("%H:%M")


def _reconcile_counts(expected: dict[str, int], loaded: dict[str, int]) -> None:
    observed = {
        "bars": loaded.get("Bar", 0),
        "trades": loaded.get("TradeTick", 0),
        "orderbook": loaded.get("OrderBookDepth10", 0),
    }
    if observed != expected:
        raise ValueError(f"DNSE raw and catalog record counts differ: {expected} != {observed}")
