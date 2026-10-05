from __future__ import annotations

from datetime import date
from datetime import datetime

import pandas as pd

from nautilus_trader.model import BarType
from nautilus_trader.persistence import ParquetDataCatalog

from nautilus_bridge.data.catalog import catalog_path

VN_TZ = "Asia/Ho_Chi_Minh"
LOOKBACK_TRADING_DAYS = 30


def trading_day(ts: int) -> date:
    return pd.Timestamp(ts, tz="UTC").tz_convert(VN_TZ).date()


def warmup_start(
    bar_type: BarType,
    before: datetime,
    trading_days: int,
) -> pd.Timestamp:
    """`ts_init` of the first bar on the earliest of the last `trading_days` days with bars before `before`.

    Starting at a bar instead of midnight keeps the warmup request inside the range the
    catalog covers.
    """
    before = pd.Timestamp(before)
    path = catalog_path()
    catalog = ParquetDataCatalog(str(path))

    first_ts = catalog.query_first_timestamp("bars", str(bar_type))
    if first_ts is None:
        raise ValueError(f"No {bar_type} bars in the catalog at {path}")
    first = pd.Timestamp(first_ts, tz="UTC")

    span = pd.Timedelta(days=2 * trading_days)
    while True:
        start = max(before - span, first)
        bars = catalog.query_bars([str(bar_type)], start=start.value, end=before.value - 1)
        days = _trading_dates(bars)

        if len(days) >= trading_days:
            first_day = days[-trading_days]
            first_ts_init = min(bar.ts_init for bar in bars if trading_day(bar.ts_event) == first_day)
            return pd.Timestamp(first_ts_init, tz="UTC")

        if start == first:
            raise ValueError(
                f"{len(days)} trading days of {bar_type} bars before {before.date()}, "
                f"{trading_days} needed; the earliest start with full warmup is "
                f"{_earliest_start(catalog, bar_type, first, trading_days)}",
            )

        span *= 2


def _earliest_start(
    catalog: ParquetDataCatalog,
    bar_type: BarType,
    first: pd.Timestamp,
    trading_days: int,
) -> object:
    end = first + pd.Timedelta(days=4 * trading_days)
    bars = catalog.query_bars([str(bar_type)], start=first.value, end=end.value)
    days = _trading_dates(bars)

    return days[trading_days] if len(days) > trading_days else "unknown"


def _trading_dates(bars: list) -> list:
    return sorted({trading_day(bar.ts_event) for bar in bars})
