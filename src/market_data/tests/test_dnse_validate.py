"""Test which DNSE one-minute bar layouts the raw delivery check accepts."""

from __future__ import annotations

import json
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from market_data.sources.dnse.validate import validate_raw_delivery


DAY = "2026-10-22"
SYMBOL = "41I1GB000"
LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")


def session_opens(*extra: str) -> list[int]:
    """Bar opens of the 241-bar session grid plus ``extra`` local minutes, in time order."""
    start = datetime.fromisoformat(f"{DAY}T09:00").replace(tzinfo=LOCAL)
    morning = [start + timedelta(minutes=value) for value in range(150)]
    afternoon = [start.replace(hour=13) + timedelta(minutes=value) for value in range(90)]
    added = [datetime.fromisoformat(f"{DAY}T{minute}").replace(tzinfo=LOCAL) for minute in extra]
    closing = start.replace(hour=14, minute=45)
    return sorted(int(value.timestamp()) for value in [*morning, *afternoon, *added, closing])


def write_raw_day(root, opens: list[int]) -> None:
    futures = root / "hnx" / "futures"
    bars = futures / "bars" / "VN30F1M" / f"1m_{DAY.replace('-', '')}_{DAY.replace('-', '')}.json"
    bars.parent.mkdir(parents=True)
    bars.write_text(json.dumps({key: opens if key == "t" else [1] * len(opens) for key in "tohlcv"}))
    row = {"symbol": SYMBOL, "marketId": "DVX", "boardId": "G1", "isin": "VN41I1GB0001", "time": f"{DAY} 09:00:01"}
    trade = {**row, "matchQtty": 1, "totalVolumeTraded": 1}
    for category, key, record in (("trades", "trades", trade), ("orderbook", "quotes", row)):
        page = futures / category / SYMBOL / DAY / "page_00001.json"
        page.parent.mkdir(parents=True)
        page.write_text(json.dumps({key: [record]}))


def test_a_session_boundary_bar_is_counted_with_the_preceding_minute(tmp_path):
    write_raw_day(tmp_path, session_opens("14:30"))

    validation = validate_raw_delivery(tmp_path)

    assert validation.counts["bars"] == 241
    assert validation.missing_bar_timestamps == ()


def test_another_out_of_session_bar_is_rejected(tmp_path):
    write_raw_day(tmp_path, session_opens("14:31"))

    with pytest.raises(ValueError, match="out-of-session"):
        validate_raw_delivery(tmp_path)
