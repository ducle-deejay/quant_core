# spec: 40-tests.md B — artifact contracts (pool, schema version, series)

import pandas as pd
import pytest

from core import Instrument
from core.artifacts import (
    AlphaPool,
    Composite,
    PoolEntry,
    PoolSchemaError,
    SpecSheet,
    TargetSeries,
    TearSheet,
    Window,
)

W = Window(
    instrument_id="VN30F1M.HNX",
    bar_type="1-MINUTE-LAST-EXTERNAL",
    start=pd.Timestamp("2026-06-01", tz="UTC"),
    end=pd.Timestamp("2026-06-05", tz="UTC"),
    n_bars=100,
)

TS = pd.date_range("2026-06-01", periods=5, freq="min", tz="UTC")


def make_entry(alpha_id="a1", verdict="IN"):
    tear = TearSheet(
        alpha_id=alpha_id,
        dsl="close - ewma(close, 8)",
        metrics={"net_sharpe": 1.23},
        verdict=verdict,
        reasons=(),
        provenance={},
    )
    spec = SpecSheet(
        alpha_id=alpha_id,
        expected_holding_period_bars=5,
        expected_net_sharpe=1.0,
        expected_ic={"1": 0.03},
        cost_model_bps=2.294,
        capacity_contracts=3,
    )
    return PoolEntry(
        alpha_id=alpha_id,
        dsl="close - ewma(close, 8)",
        tear_sheet=tear,
        spec_sheet=spec,
    )


def test_pool_roundtrip_preserves_tear_and_spec(tmp_path):
    pool = AlphaPool(instrument="VN30F1M")
    pool.add(make_entry("a1"))
    pool.add(make_entry("a2"))
    pool.save(tmp_path)
    loaded = AlphaPool.load(tmp_path)
    assert [e.alpha_id for e in loaded.entries] == ["a1", "a2"]
    e = loaded.entries[0]
    assert e.tear_sheet.metrics["net_sharpe"] == 1.23
    assert e.spec_sheet.expected_ic == {"1": 0.03}
    assert e.spec_sheet.cost_model_bps == 2.294
    assert e.schema_version == "2"


def test_pool_load_rejects_v1_schema(tmp_path):
    legacy = {
        "alpha_id": "old",
        "dsl": "x",
        "schema_version": "1",
    }
    (tmp_path / "alphas").mkdir()
    import json

    (tmp_path / "alphas" / "old.json").write_text(json.dumps(legacy))
    with pytest.raises(PoolSchemaError, match="re-deliver"):
        AlphaPool.load(tmp_path)


def test_composite_validations():
    import numpy as np

    with pytest.raises(ValueError):
        Composite(
            alpha_ids=("a", "b"),
            weights=(1.0,),
            scores=np.zeros(3),
            window=W,
            method="inverse_vol",
        )
    with pytest.raises(ValueError):
        Composite(
            alpha_ids=("a",),
            weights=(1.0,),
            scores=np.array([float("nan"), 0.0]),
            window=W,
            method="inverse_vol",
        )


def test_target_series_validations_and_to_frame():
    import numpy as np

    instr = Instrument.load("VN30F1M")
    good = TargetSeries.from_arrays(
        ts=TS, target_contracts=np.array([0, 1, 1, -2, 0]), window=W, instrument=instr
    )
    frame = good.to_frame()
    assert list(frame.columns) == ["ts", "target_contracts"]
    assert len(frame) == 5
    with pytest.raises(ValueError):
        TargetSeries.from_arrays(
            ts=TS[:-1], target_contracts=np.zeros(5), window=W, instrument=instr
        )


def test_window_mismatch_type_exists_and_is_value_error():
    from core.artifacts import WindowMismatch

    assert issubclass(WindowMismatch, ValueError)
