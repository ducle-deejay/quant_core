"""Unit tests for the quant_api execution module (decision note DEC-017).

Governing notes: DEC-017; canon Component 6 - Trade Scheduling (urgency,
order discipline), feedback 7->1 (slippage -> cost model).

Run: `.venv/bin/python3 src/quant_api/tests/test_execution.py` (repo root).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from quant_api.core import DataConfig
from quant_api.execution import (
    ExecutionConfig,
    backtest_execution,
    execution_algorithms,
    slippage_report,
    urgency_analysis,
)


def test_urgency_analysis_math() -> None:
    # Waiting is expensive -> act now.
    out = urgency_analysis(
        gap_contracts=2,
        half_spread_bps=4.0,
        impact_bps=1.0,
        alpha_decay_per_bar=10.0,
        value_of_1bp=1000.0,
    )
    assert out["verdict"] == "act-now"
    assert out["cost_of_waiting"] > out["cost_of_acting"]
    # Acting is expensive -> slice.
    out2 = urgency_analysis(2, 40.0, 60.0, 1.0, 1000.0)
    assert out2["verdict"] == "slice"
    # Zero gap -> both zero, slice (no urgency).
    out3 = urgency_analysis(0, 4.0, 1.0, 10.0, 1000.0)
    assert out3["cost_of_waiting"] == 0.0 and out3["verdict"] == "slice"
    try:
        urgency_analysis(-1, 1, 1, 1, 1)
        raise AssertionError("negative gap accepted")
    except ValueError:
        pass


def test_execution_algorithms_registry() -> None:
    cfg = ExecutionConfig(slice_bars=4)
    assert execution_algorithms.get("marketable_limit").source == "engine"
    assert execution_algorithms.get("twap").source == "python"
    assert execution_algorithms.call("marketable_limit", 5, cfg) == [5]
    assert execution_algorithms.call("marketable_limit", 0, cfg) == []
    assert execution_algorithms.call("twap", 10, cfg) == [3, 3, 2, 2]
    assert sum(execution_algorithms.call("twap", -10, cfg)) == -10
    assert execution_algorithms.call("twap", 0, cfg) == []


def test_slippage_report_synthetic() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="qa_exec_"))
    fills = [
        {"price": 100.10, "decision_mid": 100.00, "side": 1, "ts": "2026-08-28T09:05:00"},
        {"price": 99.90, "decision_mid": 100.00, "side": -1, "ts": "2026-08-28T09:15:00"},
        {"price": 100.05, "decision_mid": 100.00, "side": 1, "ts": "2026-08-28T13:05:00"},
    ]
    out = slippage_report(fills=fills, save=True, week="2026-08-31", root=tmp / "research")
    assert out["n_records"] == 3
    assert abs(out["mean_shortfall_bps"] - 25.0 / 3.0) < 1e-6  # (10 + 10 + 5)/3 bps
    assert set(out["by_session_hour"]) == {"09", "13"}
    saved = json.loads((tmp / "research" / "slippage_2026-08-31.json").read_text())
    assert saved["n_records"] == 3
    try:
        slippage_report()
        raise AssertionError("no input accepted")
    except ValueError:
        pass


def test_backtest_execution_smoke() -> None:
    """End-to-end Nautilus backtest on a 1-day catalog window (241 bars)."""
    from quant_api.core import load_bars

    window = DataConfig(start="2026-08-28", end="2026-08-29")
    df = load_bars(window)
    ts = df["ts"]
    targets = ts.iloc[[60, 120, 180]].reset_index(drop=True)
    target_df = targets.to_frame(name="ts").assign(target_contracts=[2, -1, 0])
    cfg = ExecutionConfig(cooldown_secs=0.0, min_gap_contracts=0)
    report = backtest_execution(target_df, config=cfg, data=window, algo="marketable_limit")
    assert report["n_target_changes"] == 3
    assert report["n_orders"] >= 1
    assert report["n_fills"] >= 1
    assert report["n_rejected"] == 0
    assert report["slippage_bps_mean"] == report["slippage_bps_mean"]  # finite
    assert report["provenance"]["algo_source"] == "engine"


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
    print(f"EXECUTION TESTS: {len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
