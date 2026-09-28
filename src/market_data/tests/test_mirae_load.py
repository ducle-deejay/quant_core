"""Test the Mirae day-level bar backfill and the bar ts_init convention.

Covers filling a DNSE gap inside an already written day (which previously failed
with a non-disjoint interval), keeping complete DNSE days, merging when neither
source is complete, and the one-minute ts_init offset with the ATC exception.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nautilus_trader.model import Bar  # noqa: E402
from nautilus_trader.model import BarType  # noqa: E402
from nautilus_trader.persistence import ParquetDataCatalog  # noqa: E402

from market_data.sources.mirae.load import load_day  # noqa: E402
from market_data.sources.mirae.transform import BAR_TYPE  # noqa: E402
from market_data.sources.mirae.transform import _bar_ts_init  # noqa: E402
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import (  # noqa: E402
    build_continuous_futures_contract,
)


INSTRUMENT = build_continuous_futures_contract()
ONE_MINUTE_NS = 60_000_000_000
LOCAL_TIMEZONE = "Asia/Ho_Chi_Minh"


def session_open_times(day: str) -> list[pd.Timestamp]:
    """The canonical 241 one-minute open times of a VN30F1M session, in UTC."""
    local = [
        *pd.date_range(f"{day} 09:00", f"{day} 11:29", freq="min"),
        *pd.date_range(f"{day} 13:00", f"{day} 14:29", freq="min"),
        pd.Timestamp(f"{day} 14:45"),
    ]
    return [t.tz_localize(LOCAL_TIMEZONE).tz_convert("UTC") for t in local]


def make_bars(times: list[pd.Timestamp], close: float) -> list[Bar]:
    bar_type = BarType.from_str(BAR_TYPE)
    price = INSTRUMENT.make_price(close)
    return [
        Bar(
            bar_type,
            price,
            price,
            price,
            price,
            INSTRUMENT.make_qty(1),
            t.value,
            _bar_ts_init(t, t.value),
        )
        for t in times
    ]


def catalog_bars(path: Path) -> dict[int, float]:
    catalog = ParquetDataCatalog(str(path))
    return {bar.ts_event: bar.close.as_double() for bar in catalog.query_bars([BAR_TYPE])}


def seed(path: Path, bars: list[Bar]) -> None:
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([INSTRUMENT])
    catalog.write_bars(bars)


def test_ts_init_is_minute_close_except_atc():
    times = session_open_times("2026-09-29")
    ts_init = [_bar_ts_init(t, t.value) - t.value for t in times]
    assert ts_init[:-1] == [ONE_MINUTE_NS] * 240
    assert ts_init[-1] == 0  # 14:45 ATC print


def test_complete_mirae_day_replaces_dnse_day_with_a_gap(tmp_path):
    times = session_open_times("2026-09-29")
    gap = times[75]  # 10:15 local, inside the DNSE-written day
    seed(tmp_path, make_bars([t for t in times if t != gap], close=100.0))

    report = load_day(catalog_path=tmp_path, transformed=[make_bars(times, close=200.0)])

    stored = catalog_bars(tmp_path)
    assert len(stored) == 241
    assert set(stored.values()) == {200.0}  # the whole day now comes from Mirae
    assert report["Bar"] == 241 and report.get("SkippedBar", 0) == 0
    assert report["added_bar_timestamps"] == [gap.value]


def test_complete_dnse_day_is_kept(tmp_path):
    times = session_open_times("2026-09-29")
    seed(tmp_path, make_bars(times, close=100.0))

    report = load_day(catalog_path=tmp_path, transformed=[make_bars(times, close=200.0)])

    assert set(catalog_bars(tmp_path).values()) == {100.0}
    assert report.get("Bar", 0) == 0 and report["SkippedBar"] == 241
    assert report["added_bar_timestamps"] == []


def test_incomplete_sources_merge_with_dnse_first(tmp_path):
    times = session_open_times("2026-09-29")
    dnse_gap, mirae_gap, both_gap = times[10], times[20], times[30]
    seed(tmp_path, make_bars([t for t in times if t not in (dnse_gap, both_gap)], close=100.0))
    mirae = make_bars([t for t in times if t not in (mirae_gap, both_gap)], close=200.0)

    report = load_day(catalog_path=tmp_path, transformed=[mirae])

    stored = catalog_bars(tmp_path)
    assert len(stored) == 240 and both_gap.value not in stored
    assert stored[dnse_gap.value] == 200.0  # filled from Mirae
    assert stored[mirae_gap.value] == 100.0  # DNSE value kept
    assert report["Bar"] == 1 and report["SkippedBar"] == 238
    assert report["added_bar_timestamps"] == [dnse_gap.value]


def test_multi_day_batch_only_rewrites_incomplete_days(tmp_path):
    day1, day2 = session_open_times("2026-09-28"), session_open_times("2026-09-29")
    gap = day2[-2]  # 14:29 local, the last bar before ATC
    seed(tmp_path, make_bars(day1 + [t for t in day2 if t != gap], close=100.0))

    report = load_day(catalog_path=tmp_path, transformed=[make_bars(day1 + day2, close=200.0)])

    stored = catalog_bars(tmp_path)
    assert len(stored) == 482
    assert {stored[t.value] for t in day1} == {100.0}
    assert {stored[t.value] for t in day2} == {200.0}
    assert report["added_bar_timestamps"] == [gap.value]


def test_absent_day_inside_a_multi_day_file_is_backfilled(tmp_path):
    day1, day2, day3 = (session_open_times(d) for d in ("2026-09-28", "2026-09-29", "2026-09-30"))
    seed(tmp_path, make_bars(day1 + day3, close=100.0))  # one file whose interval spans day2

    report = load_day(catalog_path=tmp_path, transformed=[make_bars(day2, close=200.0)])

    stored = catalog_bars(tmp_path)
    assert len(stored) == 723
    assert {stored[t.value] for t in day2} == {200.0}
    assert {stored[t.value] for t in day1 + day3} == {100.0}
    assert report["added_bar_timestamps"] == [t.value for t in day2]


def test_pipeline_count_check_accepts_merged_session_boundary_records(tmp_path, monkeypatch):
    import json
    from datetime import date

    from market_data.sources.mirae import pipeline

    day = "2026-09-29"
    # Full-history payloads carry 11:30 and 14:30 records that Transform merges into 11:29 / 14:29
    boundary = [pd.Timestamp(f"{day} {hm}").tz_localize(LOCAL_TIMEZONE).tz_convert("UTC") for hm in ("11:30", "14:30")]
    times = sorted(session_open_times(day) + boundary)
    bars_dir = tmp_path / "raw" / day / "hnx" / "futures" / "bars" / "VN30F1M"
    bars_dir.mkdir(parents=True)
    n = len(times)
    payload = {"t": [int(t.timestamp()) for t in times], "o": [100.0] * n, "h": [100.0] * n,
               "l": [100.0] * n, "c": [100.0] * n, "v": [1] * n}
    (bars_dir / "1m_20260929_20260929.json").write_text(json.dumps(payload))
    monkeypatch.setattr(pipeline, "extract_day", lambda **_: None)
    (tmp_path / "catalog").mkdir()

    report = pipeline.run_daily(
        request_history=None,
        active_contract=None,
        raw_root=tmp_path / "raw",
        catalog_path=tmp_path / "catalog",
        continuous_symbol="VN30F1M",
        day=date.fromisoformat(day),
    )

    assert n == 243
    assert report["records"]["Bar"] == 241
    assert len(catalog_bars(tmp_path / "catalog")) == 241
