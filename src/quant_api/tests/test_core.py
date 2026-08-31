"""Unit tests for quant_api.core (decision note DEC-017).

Covers the shared foundation the four role modules build on: registry
semantics, pool folder round-trip, artifact writers, catalog data access.

Run: `.venv/bin/python3 src/quant_api/tests/test_core.py` (repo root).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from quant_api.core.artifacts import (
    append_trial_ledger,
    write_risk_overlay_config,
    write_slippage_summary,
    write_weights,
)
from quant_api.core.config import DataConfig, DEFAULT_BAR_TYPE
from quant_api.core.data import close_volume, load_bars
from quant_api.core.pool import (
    PoolEntry,
    load_index,
    load_pool,
    write_pool_entry,
    write_pool_index,
)
from quant_api.core.registry import Registry


def test_registry_semantics() -> None:
    r = Registry("slot_x")
    r.register("a", lambda x: x + 1, source="engine")
    r.register("b", lambda x: x * 2)
    assert r.call("a", 1) == 2 and r.call("b", 2) == 4
    assert r.names() == ["a", "b"]
    assert {m["source"] for m in r.describe()} == {"engine", "python"}
    try:
        r.register("a", lambda x: x)
        raise AssertionError("duplicate accepted")
    except ValueError:
        pass
    r.register("a", lambda x: x, replace=True)  # explicit override allowed
    try:
        r.get("nope")
        raise AssertionError("unknown method accepted")
    except KeyError:
        pass
    try:
        r.register("c", "not callable")
        raise AssertionError("non-callable accepted")
    except ValueError:
        pass
    try:
        r.register("d", lambda x: x, source="rust")
        raise AssertionError("bad source accepted")
    except ValueError:
        pass


def test_pool_round_trip() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="qa_core_"))
    e1 = PoolEntry(alpha_id="a-1", dsl="close - ewma(close, 8)", tags=("trend",), spec_sheet={"x": 1})
    e2 = PoolEntry(alpha_id="a-2", dsl="ts_returns(close, 8)", family="mom")
    write_pool_entry(e1, root=tmp)
    write_pool_entry(e2, root=tmp)
    write_pool_index([e1, e2], root=tmp)
    pool = load_pool(tmp)
    assert [e.alpha_id for e in pool] == ["a-1", "a-2"]
    assert pool[0].tags == ("trend",) and pool[0].spec_sheet == {"x": 1}
    index = load_index(tmp)
    assert index["count"] == 2
    # Corrupt entry -> clear error.
    (tmp / "alphas" / "bad.json").write_text("{not json")
    try:
        load_pool(tmp)
        raise AssertionError("corrupt entry accepted")
    except ValueError:
        pass


def test_artifact_writers() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="qa_core_"))
    led = append_trial_ledger({"alpha_id": "a", "verdict": "IN"}, root=tmp / "research")
    append_trial_ledger({"alpha_id": "b", "verdict": "OUT"}, root=tmp / "research")
    lines = led.read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["verdict"] == "IN"

    w = write_weights({"a": 0.5}, root=tmp / "pool")
    assert json.loads(w.read_text())["a"] == 0.5

    s = write_slippage_summary({"mean_bps": 1.2}, week="2026-08-31", root=tmp / "research")
    assert "slippage_2026-08-31" in s.name

    o = write_risk_overlay_config({"risk": {}}, root=tmp / "state")
    assert json.loads(o.read_text())["risk"] == {}


def test_data_catalog_window() -> None:
    cfg = DataConfig(start="2026-08-28", end="2026-08-29")
    df = load_bars(cfg)
    assert len(df) == 241
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert df["ts"].is_monotonic_increasing
    close, volume = close_volume(df)
    assert len(close) == len(volume) == 241
    assert all(isinstance(v, float) for v in close[:5])
    # Full-history default resolves without error (first/last sanity).
    full = load_bars()
    assert len(full) > 100_000
    assert cfg.bar_type == DEFAULT_BAR_TYPE


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[FAIL] {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"CORE TESTS: {len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
