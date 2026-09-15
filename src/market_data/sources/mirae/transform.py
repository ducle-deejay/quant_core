from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType

from market_data.sources.mirae.quality import read_json
from market_data.instruments import build_continuous_futures_contract
from market_data.instruments import load_futures_instrument_spec
from market_data.instruments import register_futures_instrument_currency


BAR_TYPE = "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL"


def transform_day(
    *,
    raw_day: str | Path,
    instrument_config: str | Path,
) -> Iterator[list[Any]]:
    """Transform one retained Mirae candlestick ingestion into Nautilus objects."""
    spec = load_futures_instrument_spec(instrument_config)
    register_futures_instrument_currency(spec)
    continuous = build_continuous_futures_contract(
        spec,
        ts_event_ns=_ingestion_day_ts_ns(Path(raw_day)),
        record_ts_init_ns=_ingestion_day_ts_ns(Path(raw_day)),
    )
    yield [continuous]

    root = Path(raw_day) / "hnx" / "futures" / "bars"
    for path in sorted(root.glob("*/*.json")):
        yield _transform_bars(path, continuous)


def _transform_bars(path: Path, instrument: Any) -> list[Any]:
    payload = read_json(path)
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(payload["t"], unit="s", utc=True).floor("min"),
            "open": payload["o"],
            "high": payload["h"],
            "low": payload["l"],
            "close": payload["c"],
            "volume": payload["v"],
        },
    ).sort_values("timestamp", kind="stable")
    frame = frame.drop_duplicates(subset="timestamp", keep="last")
    bar_type = BarType.from_str(BAR_TYPE)
    bars: list[Bar] = []
    for timestamp, open_, high, low, close, volume in zip(
        frame["timestamp"],
        frame["open"],
        frame["high"],
        frame["low"],
        frame["close"],
        frame["volume"],
        strict=True,
    ):
        ts_event = int(pd.Timestamp(timestamp).value)
        bars.append(
            Bar(
                bar_type,
                instrument.make_price(open_),
                instrument.make_price(high),
                instrument.make_price(low),
                instrument.make_price(close),
                instrument.make_qty(volume),
                ts_event,
                ts_event,
            ),
        )
    return bars


def _ingestion_day_ts_ns(raw_day: Path) -> int:
    """Stamp instrument definitions at the ingestion day's UTC midnight, so the
    definition precedes that day's data and replays stay deterministic."""
    from datetime import date

    return int(pd.Timestamp(date.fromisoformat(raw_day.name), tz="UTC").value)
