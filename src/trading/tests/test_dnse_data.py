"""DNSE data client historical-source tests (governing note: DEC-008 warmup wiring).

Warmup bars must be served from the research ETL catalog (data/catalog,
ParquetDataCatalog) instead of the holey DNSE REST API, with a warning and a
fallback to the API when the catalog yields no bars for the requested window,
and the ``api`` source must keep the previous behavior. No network calls: the
REST client is stubbed and the catalog is a tmp ParquetDataCatalog.

Runs under pytest when available, and also as a plain assert runner:

    .venv/bin/python3 src/trading/tests/test_dnse_data.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import traceback
from datetime import datetime
from datetime import timezone
from pathlib import Path

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import MessageBus
from nautilus_trader.common.component import TestClock
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.data.messages import RequestBars
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AggregationSource
from nautilus_trader.model.identifiers import ClientId
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from trading.adapters.dnse.config import DnseDataClientConfig
from trading.adapters.dnse.data import DEFAULT_CATALOG_PATH
from trading.adapters.dnse.data import DnseLiveDataClient
from trading.adapters.dnse.data import _load_catalog_bars
from trading.adapters.dnse.data import build_bar_type_for_symbol
from trading.adapters.dnse.instruments import DnseInstrumentProvider
from trading.instruments import load_futures_instrument_spec

UTC = timezone.utc
BAR_TYPE = build_bar_type_for_symbol(symbol="VN30F1M", resolution="1", venue="HNX")
INSTRUMENT_SPEC = load_futures_instrument_spec(
    Path(__file__).resolve().parents[2]
    / "market_data"
    / "instrument_definitions"
    / "vn30f1m.hnx.json",
)

# Two bars on the trading day 2026-08-28 (Friday), 02:01 and 02:02 UTC.
CANNED_OHLC_BODY = {
    "t": [1787882460, 1787882520],
    "o": [2000.0, 2001.0],
    "h": [2002.0, 2003.0],
    "l": [1999.0, 2000.0],
    "c": [2001.0, 2002.0],
    "v": [1000, 1100],
}


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _make_bars(
    bar_type: BarType = BAR_TYPE,
    n: int = 3,
    start_minute: int = 0,
    base: float = 100.0,
) -> list[Bar]:
    bars: list[Bar] = []
    for i in range(n):
        ts = int(_utc(2026, 8, 28, 2, start_minute + i).timestamp()) * 1_000_000_000
        bars.append(
            Bar(
                bar_type,
                Price(base + i, 1),
                Price(base + 1 + i, 1),
                Price(base - 1 + i, 1),
                Price(base + 0.5 + i, 1),
                Quantity(100 + i, 0),
                ts,
                ts,
            ),
        )
    return bars


def _make_catalog(bars: list[Bar] | None = None) -> ParquetDataCatalog:
    tmp = Path(tempfile.mkdtemp(prefix="dnse_test_catalog_"))
    catalog = ParquetDataCatalog.from_uri(tmp.as_uri())
    if bars:
        catalog.write_data(bars, skip_disjoint_check=True)
    return catalog


class _FakeRestClient:
    def __init__(self, body: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.body: dict = body if body is not None else CANNED_OHLC_BODY

    def get_ohlc(self, **kwargs) -> tuple[int, dict]:
        self.calls.append(kwargs)
        return 200, self.body

    def get_working_dates(self, **kwargs) -> tuple[int, list]:
        return 200, []


class _FakeTradingClient:
    def on(self, *args, **kwargs) -> None:
        return None


class _BarsRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, bar_type, bars, **kwargs) -> None:
        self.calls.append({"bar_type": bar_type, "bars": bars, "kwargs": kwargs})


def _make_client(config: DnseDataClientConfig, rest_client) -> tuple[DnseLiveDataClient, asyncio.AbstractEventLoop]:
    clock = TestClock()
    msgbus = MessageBus(trader_id=TraderId("TEST-001"), clock=clock)
    cache = Cache()
    provider = DnseInstrumentProvider(config)
    loop = asyncio.new_event_loop()
    client = DnseLiveDataClient(
        loop=loop,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=provider,
        config=config,
        trading_client=_FakeTradingClient(),
        rest_client=rest_client,
    )
    return client, loop


def _make_request(
    start: datetime,
    end: datetime,
    bar_type: BarType = BAR_TYPE,
) -> RequestBars:
    return RequestBars(
        bar_type=bar_type,
        start=start,
        end=end,
        limit=0,
        client_id=ClientId("DNSE"),
        venue=None,
        callback=None,
        request_id=UUID4(),
        ts_init=0,
        params=None,
    )


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #


def test_historical_source_default_and_allowed_values():
    config = DnseDataClientConfig(
        api_key="k",
        api_secret="s",
        instrument_spec=INSTRUMENT_SPEC,
    )
    assert config.historical_source == "catalog"
    assert config.catalog_path is None

    api_config = DnseDataClientConfig(
        api_key="k",
        api_secret="s",
        instrument_spec=INSTRUMENT_SPEC,
        historical_source="api",
    )
    assert api_config.historical_source == "api"


def test_historical_source_rejects_unknown_value():
    try:
        DnseDataClientConfig(
            api_key="k",
            api_secret="s",
            instrument_spec=INSTRUMENT_SPEC,
            historical_source="bogus",
        )
    except ValueError:
        return
    raise AssertionError("unknown historical_source must raise ValueError")


def test_catalog_path_default_resolves_to_repo_catalog():
    config = DnseDataClientConfig(
        api_key="k",
        api_secret="s",
        instrument_spec=INSTRUMENT_SPEC,
    )
    client, loop = _make_client(config, _FakeRestClient())
    assert client._catalog is not None
    assert Path(client._catalog.path) == DEFAULT_CATALOG_PATH.resolve()


# --------------------------------------------------------------------------- #
# catalog source serves catalog bars
# --------------------------------------------------------------------------- #


def test_catalog_source_serves_catalog_bars():
    catalog_bars = _make_bars(n=3, start_minute=0)
    catalog = _make_catalog(catalog_bars)
    config = DnseDataClientConfig(
        api_key="k",
        api_secret="s",
        instrument_spec=INSTRUMENT_SPEC,
        historical_source="catalog",
        catalog_path=str(catalog.path),
    )
    rest = _FakeRestClient()
    client, loop = _make_client(config, rest)
    recorder = _BarsRecorder()
    client._handle_bars = recorder

    loop.run_until_complete(
        client._request_bars(
            _make_request(start=_utc(2026, 8, 28, 2, 0), end=_utc(2026, 8, 28, 2, 2)),
        ),
    )

    assert len(recorder.calls) == 1
    served = recorder.calls[0]["bars"]
    assert len(served) == 3
    assert [bar.ts_event for bar in served] == [bar.ts_event for bar in catalog_bars]
    assert [bar.ts_init for bar in served] == [bar.ts_event for bar in catalog_bars]
    assert all(bar.bar_type == BAR_TYPE for bar in served)
    assert served[0].open == catalog_bars[0].open
    assert served[0].close == catalog_bars[0].close
    assert served[0].volume == catalog_bars[0].volume
    assert rest.calls == [], "DNSE API must not be called when the catalog serves bars"


# --------------------------------------------------------------------------- #
# empty catalog window falls back to the API
# --------------------------------------------------------------------------- #


def test_catalog_empty_window_falls_back_to_api():
    # Catalog holds bars outside the requested window, so the window query is empty.
    catalog = _make_catalog(_make_bars(n=2, start_minute=30))
    config = DnseDataClientConfig(
        api_key="k",
        api_secret="s",
        instrument_spec=INSTRUMENT_SPEC,
        historical_source="catalog",
        catalog_path=str(catalog.path),
    )
    rest = _FakeRestClient()
    client, loop = _make_client(config, rest)
    recorder = _BarsRecorder()
    client._handle_bars = recorder

    loop.run_until_complete(
        client._request_bars(
            _make_request(start=_utc(2026, 8, 28, 2, 0), end=_utc(2026, 8, 28, 2, 10)),
        ),
    )

    assert len(recorder.calls) == 1
    served = recorder.calls[0]["bars"]
    assert len(rest.calls) == 1, "empty catalog window must fall back to the DNSE API"
    assert len(served) == 2
    assert all(bar.bar_type == BAR_TYPE for bar in served)
    assert [bar.ts_event for bar in served] == [
        int(_utc(2026, 8, 28, 2, 1).timestamp()) * 1_000_000_000,
        int(_utc(2026, 8, 28, 2, 2).timestamp()) * 1_000_000_000,
    ]


# --------------------------------------------------------------------------- #
# api source keeps the old behavior (catalog untouched)
# --------------------------------------------------------------------------- #


def test_api_source_keeps_old_behavior():
    catalog = _make_catalog(_make_bars(n=2, start_minute=0, base=500.0))
    config = DnseDataClientConfig(
        api_key="k",
        api_secret="s",
        instrument_spec=INSTRUMENT_SPEC,
        historical_source="api",
        catalog_path=str(catalog.path),
    )
    rest = _FakeRestClient()
    client, loop = _make_client(config, rest)
    recorder = _BarsRecorder()
    client._handle_bars = recorder

    loop.run_until_complete(
        client._request_bars(
            _make_request(start=_utc(2026, 8, 28, 2, 0), end=_utc(2026, 8, 28, 2, 2)),
        ),
    )

    assert client._catalog is None, "api source must not construct a catalog"
    assert len(rest.calls) == 1
    assert len(recorder.calls) == 1
    served = recorder.calls[0]["bars"]
    assert len(served) == 2
    assert all(bar.bar_type == BAR_TYPE for bar in served)
    # Canned API body (base 2000) must win over the catalog bars (base 500).
    assert served[0].open.as_double() == 2000.0


# --------------------------------------------------------------------------- #
# pure helper: _load_catalog_bars window filtering
# --------------------------------------------------------------------------- #


def test_load_catalog_bars_window_filtering():
    catalog = _make_catalog(_make_bars(n=5, start_minute=0))
    all_bars = _load_catalog_bars(catalog, BAR_TYPE, start=None, end=None)
    assert len(all_bars) == 5

    window = _load_catalog_bars(
        catalog,
        BAR_TYPE,
        start=_utc(2026, 8, 28, 2, 2),
        end=_utc(2026, 8, 28, 2, 4),
    )
    assert len(window) == 3
    assert [bar.ts_event for bar in window] == [
        int(_utc(2026, 8, 28, 2, 2 + i).timestamp()) * 1_000_000_000 for i in range(3)
    ]

    empty = _load_catalog_bars(
        catalog,
        BAR_TYPE,
        start=_utc(2026, 8, 28, 5, 0),
        end=_utc(2026, 8, 28, 5, 10),
    )
    assert empty == []


# --------------------------------------------------------------------------- #
# plain assert runner (pytest is not installed in .venv)
# --------------------------------------------------------------------------- #


def _run_all() -> int:
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:  # noqa: BLE001 - plain runner reports every failure
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    total = len(tests)
    print(f"\n{total - failures}/{total} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
