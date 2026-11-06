from __future__ import annotations

from typing import Any

import pandas as pd

from market_data.sources.bar_download import columnar_frame
from market_data.sources.bar_download import get_json


# The chart data request of https://trading.vietcap.com.vn; observed to return countBack bars ending at "to"
URL = "https://api.vietcap.com.vn/ohlc-chart-service/v1/gap-chart"
COUNT_BACK = 300  # more than the session minutes of a day


def request_bars(symbol: str, start: int, end: int) -> Any:
    return get_json(
        URL,
        origin="https://trading.vietcap.com.vn",
        fields={"symbol": symbol, "to": end, "timeFrame": "ONE_MINUTE", "countBack": COUNT_BACK},
    )


def bars_frame(payload: Any) -> pd.DataFrame:
    return columnar_frame(payload.get("data") or {})
