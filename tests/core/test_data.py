# spec: 40-tests.md B12 + F25/26 — instrument facts and BarFrame/CatalogClient

import pandas as pd
import pytest

from core import CostModel, Instrument


def test_instrument_load_facts():
    inst = Instrument.load("VN30F1M")
    assert inst.symbol == "VN30F1M"
    assert inst.venue == "HNX"
    assert inst.multiplier == 100_000.0
    assert inst.tick_size == 0.1


def test_instrument_load_cached():
    assert Instrument.load("VN30F1M") is Instrument.load("VN30F1M")


def test_cost_model_defaults():
    cm = CostModel()
    assert cm.cost_per_side_frac == 0.000229
    assert cm.reference_price == 1500.0
    inst = Instrument.load("VN30F1M")
    assert inst.cost.cost_per_side_frac == cm.cost_per_side_frac


def test_unknown_instrument_raises():
    with pytest.raises(FileNotFoundError):
        Instrument.load("NOT_A_CONTRACT")


def test_barframe_rejects_bad_frames():
    from core.data import BarFrame

    good = pd.DataFrame(
        {
            "ts": pd.date_range("2026-06-01", periods=3, freq="min", tz="UTC"),
            "open": [1.0, 2.0, 3.0],
            "high": [1.0, 2.0, 3.0],
            "low": [1.0, 2.0, 3.0],
            "close": [1.0, 2.0, 3.0],
            "volume": [1.0, 1.0, 1.0],
        }
    )
    BarFrame.from_dataframe(good)  # ok
    with pytest.raises(ValueError):
        BarFrame.from_dataframe(good.drop(columns=["volume"]))
    naive = good.copy()
    naive["ts"] = naive["ts"].dt.tz_localize(None)
    with pytest.raises(ValueError):
        BarFrame.from_dataframe(naive)
    unsorted = good.iloc[[2, 1, 0]].reset_index(drop=True)
    with pytest.raises(ValueError):
        BarFrame.from_dataframe(unsorted)


@pytest.mark.integration
def test_catalogclient_bars_full_history_matches_golden_fact(full_bars, goldens):
    assert full_bars.window.n_bars == goldens["n_bars"]
    assert str(full_bars.window.start) == goldens["bars_first_ts"]
    assert str(full_bars.window.end) == goldens["bars_last_ts"]


@pytest.mark.integration
def test_catalogclient_ticks_decode(bars_fixture):
    from core.data import CatalogClient, DataConfig

    client = CatalogClient()
    ticks = client.ticks(
        "41I1G9000.HNX",
        start=pd.Timestamp("2026-08-21", tz="UTC"),
        end=pd.Timestamp("2026-08-21 08:00", tz="UTC"),
    )
    assert len(ticks) == 121_996  # fixture fact (same day, same contract)
    assert {"ts", "price", "size", "aggressor_side"} <= set(ticks.columns)
    assert ticks["price"].dtype == float
