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

import pandas as pd
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
    try:
        urgency_analysis(1, 1, 1, -1, 1)
        raise AssertionError("negative alpha_decay accepted")
    except ValueError:
        pass


def test_execution_algorithms_registry() -> None:
    cfg = ExecutionConfig(slice_bars=4)
    assert execution_algorithms.get("marketable_limit").source == "python"  # honest provenance
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
    # ts_ns (int) fills must bucket by hour too (UAT bug: backtest fills use ts_ns).
    ts_a = int(pd.Timestamp("2026-08-28T09:05:00", tz="UTC").value)
    ts_b = int(pd.Timestamp("2026-08-28T13:15:00", tz="UTC").value)
    ns_fills = [
        {"price": 100.10, "decision_mid": 100.00, "side": 1, "ts_ns": ts_a},
        {"price": 99.90, "decision_mid": 100.00, "side": -1, "ts_ns": ts_b},
    ]
    out_ns = slippage_report(fills=ns_fills, save=False)
    assert set(out_ns["by_session_hour"]) == {"16", "20"}  # normalized to Hanoi local
    # Missing decisions.jsonl -> actionable FileNotFoundError.
    try:
        slippage_report(session_dir=str(Path(tempfile.mkdtemp())))
        raise AssertionError("missing session artifacts accepted")
    except FileNotFoundError as exc:
        assert "decisions.jsonl" in str(exc) or "fills.jsonl" in str(exc)


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
    assert report["provenance"]["algo_source"] == "python"
    # UAT fixes: order-level detail + non-silent analyzer stats.
    assert "order_events" in report and isinstance(report["order_events"], list)
    assert "stats_error" in report
    # Missing-column error names the column.
    bad = df[["ts"]].iloc[:5]
    try:
        backtest_execution(bad, config=cfg, data=window)
        raise AssertionError("missing target_contracts accepted")
    except ValueError as exc:
        assert "target_contracts" in str(exc)


def test_slippage_report_bridge_log_actionable_error() -> None:
    """Practitioner review: a bridge-style decisions.jsonl (decisions only,
    no fill prices) must raise an actionable error, not a generic one."""
    tmp = Path(tempfile.mkdtemp(prefix="qa_exec_bridge_"))
    (tmp / "decisions.jsonl").write_text(
        json.dumps({"ts_event_ns": 1, "close": 1976.0, "target": 2,
                    "current_contracts": 0, "action": "submit"}) + "\n"
    )
    try:
        slippage_report(session_dir=str(tmp))
        raise AssertionError("bridge log accepted as fills")
    except ValueError as exc:
        assert "fills.jsonl" in str(exc) and "decisions" in str(exc)


def test_backtest_execution_tick_mode() -> None:
    """Tick mode: monthly contract driven by real trade ticks + depth10
    (skipped when the nox catalog is not present on this machine)."""
    nox = Path("/Users/ducle/repos/nox_system/data/catalog")
    if not nox.exists():
        print("[SKIP] test_backtest_execution_tick_mode: nox catalog not present")
        return
    from quant_api.core import DataConfig

    nox_cfg = DataConfig(catalog_path=str(nox))
    target_df = pd.DataFrame({
        "ts": pd.to_datetime(["2026-08-28T02:05:00", "2026-08-28T02:10:00",
                              "2026-08-28T02:15:00"], utc=True),
        "target_contracts": [2, -1, 0],
    })
    cfg = ExecutionConfig(cooldown_secs=0.0, min_gap_contracts=0)
    report = backtest_execution(target_df, config=cfg, data=nox_cfg,
                                algo="marketable_limit", instrument_id="41I1G9000.HNX")
    assert report["n_orders"] >= 1 and report["n_fills"] >= 1
    assert report["n_rejected"] == 0
    assert all(f["slippage_bps"] == f["slippage_bps"] for f in report["fills"])  # finite
    try:
        backtest_execution(target_df, config=cfg, data=nox_cfg, instrument_id="NOPE.HNX")
        raise AssertionError("unknown instrument accepted")
    except ValueError as exc:
        assert "not in catalog" in str(exc)


def test_backtest_execution_tick_mode_l1_no_depth() -> None:
    """Sweep finding: tick mode must run on days WITHOUT order-book depth
    (L1 fallback) instead of crashing on an empty depth collection."""
    nox = Path("/Users/ducle/repos/nox_system/data/catalog")
    if not nox.exists():
        print("[SKIP] test_backtest_execution_tick_mode_l1_no_depth: nox catalog not present")
        return
    from quant_api.core import DataConfig

    nox_cfg = DataConfig(catalog_path=str(nox))
    target_df = pd.DataFrame({
        "ts": pd.to_datetime(["2026-03-25T02:05:00", "2026-03-25T02:10:00",
                              "2026-03-25T02:15:00"], utc=True),
        "target_contracts": [2, -1, 0],
    })
    # Strict default: order-book required in tick mode (missing data must
    # raise, not degrade silently).
    strict_cfg = ExecutionConfig(cooldown_secs=0.0, min_gap_contracts=0)
    try:
        backtest_execution(target_df, config=strict_cfg, data=nox_cfg,
                           algo="marketable_limit", instrument_id="41I1G4000.HNX")
        raise AssertionError("missing order-book depth must raise")
    except ValueError as exc:
        assert "order-book depth10" in str(exc)
    # Explicit opt-in runs tick-only L1 matching and labels the mode.
    cfg = ExecutionConfig(cooldown_secs=0.0, min_gap_contracts=0, allow_l1=True)
    report = backtest_execution(target_df, config=cfg, data=nox_cfg,
                                algo="marketable_limit", instrument_id="41I1G4000.HNX")
    assert report["n_fills"] >= 1
    assert report["provenance"]["data_mode"] == "tick-l1"


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
