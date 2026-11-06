from __future__ import annotations

from typing import Any

import pandas as pd

from market_data.sources.bar_download import get_json


URL = "https://stockinfo-api-po.hsc.com.vn/v1/info/tick"  # the chart data request of https://priceonline.hsc.com.vn


def request_bars(symbol: str, start: int, end: int) -> Any:
    return get_json(f"{URL}/{symbol}/1m/{start}/{end}", origin="https://priceonline.hsc.com.vn")


def bars_frame(payload: Any) -> pd.DataFrame:
    rows = payload or []
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime([row["unixTime"] for row in rows], unit="s", utc=True),
            "open": [row["open"] for row in rows],
            "high": [row["high"] for row in rows],
            "low": [row["low"] for row in rows],
            "close": [row["close"] for row in rows],
            "volume": [row["volume"] for row in rows],
        },
    )
