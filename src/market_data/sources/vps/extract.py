from __future__ import annotations

from typing import Any

import pandas as pd

from market_data.sources.bar_download import columnar_frame
from market_data.sources.bar_download import get_json


URL = "https://histdatafeed.vps.com.vn/tradingview/history"  # the chart data request of https://chart.vps.com.vn


def request_bars(symbol: str, start: int, end: int) -> Any:
    return get_json(
        URL,
        origin="https://chart.vps.com.vn",
        fields={"symbol": symbol, "resolution": "1", "from": start, "to": end, "countback": 1000},
    )


def bars_frame(payload: Any) -> pd.DataFrame:
    return columnar_frame(payload)
