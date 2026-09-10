"""Plain-script checks for the public extension contracts and risk mapping."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from quantcore.alpha import quantitative_models, score_model
from quantcore.execution import ExecutionConfig, execution_algorithms, plan_orders
from quantcore.portfolio import combine, combine_methods
from quantcore.risk import RiskBacktestConfig, backtest_portfolio, sizing_methods
from quantcore.core import DataConfig, load_bars
from quantcore.core.extensions import (
    ExecutionAlgorithm,
    PortfolioOptimizer,
    QuantitativeModel,
    RiskMeasure,
)
from trading.contracts import RiskDecision, TargetPosition
from trading.risk.state import HALTED, REASON_LOSS, RiskConfig, RiskLedger


class Model:
    def score(self, close, volume):
        return [a + b for a, b in zip(close, volume)]


class CallableModel(Model):
    def __call__(self, close, volume):
        raise AssertionError("Registry must invoke the protocol capability")


class Optimizer:
    def optimize(self, scores):
        return [sum(row) for row in zip(*scores)]


class Measure:
    def adjust(self, z_scores, vol_est, target_vol, drawdowns=None, floor=None):
        return list(z_scores)


class Planner:
    def plan(self, gap_contracts, config):
        return [gap_contracts]


def test_protocol_registration_and_adapters() -> None:
    assert isinstance(Model(), QuantitativeModel)
    assert isinstance(Optimizer(), PortfolioOptimizer)
    assert isinstance(Measure(), RiskMeasure)
    assert isinstance(Planner(), ExecutionAlgorithm)
    quantitative_models.register("test-model", Model(), replace=True)
    assert score_model("test-model", [1.0], [2.0]) == [3.0]
    quantitative_models.register("test-callable-model", CallableModel(), replace=True)
    assert score_model("test-callable-model", [1.0], [2.0]) == [3.0]
    combine_methods.register("test-optimizer", Optimizer(), replace=True)
    combined = combine([[1.0, 2.0], [3.0, 4.0]], method="test-optimizer")
    assert combined["composite"] == [4.0, 6.0]
    sizing_methods.register("test-measure", Measure(), replace=True)
    assert sizing_methods.call("test-measure", [1.0], [0.1], 0.1, None, None) == [1.0]
    execution_algorithms.register("test-planner", Planner(), replace=True)
    assert plan_orders(2, "test-planner", ExecutionConfig()) == [2]
    try:
        quantitative_models.register("invalid-model", object(), replace=True)
        raise AssertionError("object without score capability accepted")
    except ValueError as exc:
        assert "score" in str(exc)


def test_custom_risk_measure_runs_through_backtest() -> None:
    sizing_methods.register("test-measure", Measure(), replace=True)
    data = DataConfig(start="2026-08-28", end="2026-08-29")
    bars = load_bars(data)
    report = backtest_portfolio(
        [0.0] * len(bars),
        data=data,
        sizing="test-measure",
        config=RiskBacktestConfig(data=data),
    )
    assert report["provenance"]["sizing_source"] == "python"


def test_builtin_delegation() -> None:
    assert score_model("engine_close", [1.0, 2.0], [0.0, 0.0]) == [1.0, 2.0]
    assert plan_orders(3, "marketable_limit", ExecutionConfig()) == [3]


def test_execution_algorithm_output_validation() -> None:
    execution_algorithms.register("bad-sum", lambda gap, config: [gap + 1], replace=True)
    try:
        plan_orders(2, "bad-sum", ExecutionConfig())
        raise AssertionError("invalid execution plan accepted")
    except ValueError as exc:
        assert "sum" in str(exc)


def test_risk_decision_mapping() -> None:
    ts = datetime(2026, 9, 10, 3, tzinfo=timezone.utc)
    target = TargetPosition(ts, 3, 0.2, "signal")
    ledger = RiskLedger(RiskConfig())
    assert ledger.decide_target(target).action == "approve"
    ledger.on_bar(ts)
    ledger.record_fill(1500.0, 1, ts)
    ledger.mark(1470.0, ts)
    decision = ledger.decide_target(target)
    assert decision.action == "force-flat"
    assert decision.approved_target_contracts == 0
    assert decision.reason == REASON_LOSS


if __name__ == "__main__":
    test_protocol_registration_and_adapters()
    test_custom_risk_measure_runs_through_backtest()
    test_builtin_delegation()
    test_execution_algorithm_output_validation()
    test_risk_decision_mapping()
    print("ok: extension tests")
