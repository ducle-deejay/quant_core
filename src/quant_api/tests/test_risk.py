"""Unit tests for the quant_api risk module (decision note DEC-017).

Governing notes: DEC-017; canon Component 5 - Position Construction
(sizing ownership), Component 7 - Risk Overlay and Monitoring (trigger
matrix, gauges). Vocabulary: portfolio backtest, never "replay".

Run: `.venv/bin/python3 src/quant_api/tests/test_risk.py` (repo root).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import math

from quant_api.risk import (
    RiskBacktestConfig,
    backtest_portfolio,
    build_overlay_config,
    divergence_gauges,
    post_mortem,
    risk_policies,
    sizing_methods,
)
from quant_api.core import DataConfig, HarnessParams, RiskConfig, load_bars
from trading.risk.state import RiskLedger

WINDOW = DataConfig(start="2026-07-15", end="2026-08-28")
NBARS = len(load_bars(WINDOW))


def _sine_composite(n: int = 3000) -> list[float]:
    import math as m

    return [m.sin(i / 50.0) for i in range(n)]


def test_sizing_registry_defaults() -> None:
    assert set(sizing_methods.names()) == {"drawdown_overlay", "vol_target", "vol_target_drawdown"}
    for name in sizing_methods.names():
        assert sizing_methods.get(name).source == "engine"
    z = [1.0, -1.0, 0.5]
    vol = [0.1, 0.1, 0.1]
    out = sizing_methods.call("vol_target", z, vol, 0.1, None, None)
    assert len(out) == 3 and all(math.isfinite(v) for v in out)
    dd = [0.0, 0.05, 0.1]
    mult = sizing_methods.call("drawdown_overlay", z, vol, 0.1, dd, None)
    assert all(m <= 1.0 for m in mult)
    stacked = sizing_methods.call("vol_target_drawdown", z, vol, 0.1, dd, None)
    assert len(stacked) == 3


def test_risk_policies_trigger_matrix_default() -> None:
    m = risk_policies.get("trigger_matrix")
    assert m.source == "python"
    assert "RiskLedger" in m.description


def test_backtest_portfolio_shape() -> None:
    cfg = RiskBacktestConfig(
        harness=HarnessParams(cost_per_side=0.0001),
        data=WINDOW,
    )
    composite = [math.sin(i / 60.0) for i in range(NBARS)]
    report = backtest_portfolio(composite, data=WINDOW, config=cfg)
    for side in ("before", "after"):
        assert "performance" in report[side] and "risk_process" in report[side]
        assert "net_sharpe" in report[side]["performance"]
        rp = report[side]["risk_process"]
        for key in ("n_interventions", "intervention_cost_estimate_vnd",
                    "mean_abs_tracking_error", "max_abs_position", "trigger_counts"):
            assert key in rp
    assert isinstance(report["interventions"], list)
    assert report["provenance"]["sizing_source"] == "engine"
    assert report["provenance"]["policy_source"] == "python"


def test_backtest_portfolio_length_mismatch_raises() -> None:
    try:
        backtest_portfolio([1.0, 2.0], data=DataConfig(start="2026-08-28", end="2026-08-29"))
        raise AssertionError("mismatched composite accepted")
    except ValueError:
        pass


def test_backtest_portfolio_loss_halt() -> None:
    # Tiny loss limit forces HALTED -> flatten interventions.
    risk = RiskConfig(intraday_loss_pct=0.0001, capital_vnd=100_000_000.0)
    cfg = RiskBacktestConfig(
        harness=HarnessParams(cost_per_side=0.0001),
        risk=risk,
        data=WINDOW,
    )
    composite = [math.sin(i / 30.0) for i in range(NBARS)]  # fast oscillation -> many trades
    report = backtest_portfolio(composite, data=WINDOW, config=cfg)
    assert report["after"]["risk_process"]["n_interventions"] >= 1
    assert any(i["current"] == "HALTED" for i in report["interventions"])
    triggers = report["after"]["risk_process"]["trigger_counts"]
    assert "intraday-loss-limit" in triggers


def test_divergence_gauges() -> None:
    n = 1200
    score = [math.sin(i / 40.0) for i in range(n)]
    returns = [0.001 * math.sin(i / 40.0) for i in range(n)]
    fills = [
        {"price": 100.0, "decision_mid": 99.99, "side": 1},
        {"price": 99.98, "decision_mid": 100.0, "side": -1},
    ]
    expected = {"spec_ic": 0.05, "cost_model_bps": 2.294, "tracking_error_bound": 1.0}
    live = {
        "score": score,
        "returns": returns,
        "fills": fills,
        "orders": [{}] * 4,
        "n_fills": 2,
        "current_positions": [1, 2, 1, 2],
        "target_positions": [1, 1, 1, 1],
        "feed_gaps": 0,
    }
    out = divergence_gauges(expected, live)
    assert set(out["gauges"]) == {"gauge_1", "gauge_2", "gauge_3", "gauge_4"}
    for g in out["gauges"].values():
        assert g["status"] in ("ok", "warning", "critical", "n/a")
    assert out["escalation"] in ("none", "warning", "critical")
    # Missing inputs -> n/a.
    empty = divergence_gauges({}, {})
    assert all(g["status"] == "n/a" for g in empty["gauges"].values())


def test_post_mortem_parses_session_dir() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="qa_risk_"))
    decisions = [
        {"ts_ns": 1000, "target_contracts": 0},
        {"ts_ns": 2000, "target_contracts": 4},
        {"ts_ns": 3000, "target_contracts": 1},
        {"ts_ns": 4000, "target_contracts": -5},
        {"ts_ns": 5000, "target_contracts": -2},
    ]
    transitions = [
        {"ts_ns": 1500, "previous": "ACTIVE", "current": "HALTED", "reason": "intraday-loss-limit"},
        {"ts_ns": 1600, "previous": "HALTED", "current": "ACTIVE", "reason": ""},
    ]
    (tmp / "decisions.jsonl").write_text(
        "\n".join(json.dumps(d) for d in decisions) + "\n"
    )
    (tmp / "risk_transitions.jsonl").write_text(
        "\n".join(json.dumps(t) for t in transitions) + "\n"
    )
    out = post_mortem(str(tmp))
    assert out["n_decision_events"] == 5
    assert out["n_risk_transitions"] == 2
    assert out["target_flips"] == 4
    assert out["big_gap_moves"] >= 1
    assert any(r["gate"] for r in out["recommendations"])


def test_build_overlay_config_saves() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="qa_risk_"))
    payload = build_overlay_config(save=True, root=tmp / "state")
    assert payload["risk"]["capital_vnd"] == 100_000_000.0
    assert payload["harness"]["bars_per_day"] == 240
    saved = json.loads((tmp / "state" / "risk_overlay.json").read_text())
    assert saved == payload


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
    print(f"RISK TESTS: {len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
