from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.wranglers import BarDataWrangler

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
    continuous = build_continuous_futures_contract(spec)
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
    return BarDataWrangler(BarType.from_str(BAR_TYPE), instrument).process(
        frame.set_index("timestamp")[["open", "high", "low", "close", "volume"]],
    )
