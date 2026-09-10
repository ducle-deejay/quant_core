"""Plain-script tests for the small shared trading contracts."""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from trading.contracts import RiskDecision, TargetPosition


TS = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)


def _target(value: int = 3) -> TargetPosition:
    return TargetPosition(ts=TS, target_contracts=value, z_target=0.5, reason="signal")


def _raises(exc: type[BaseException], fn) -> None:
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def test_target_is_desired_and_decision_invariants() -> None:
    target = _target()
    assert target.target_contracts == 3
    approved = RiskDecision(target, 3, "approve", "within-limit", 1)
    capped = RiskDecision(target, 2, "cap", "exposure-cap", 1)
    blocked = RiskDecision(target, 1, "block", "halted:stale-feed", 1)
    forced = RiskDecision(target, 0, "force-flat", "intraday-loss-limit", 1)
    assert approved.desired is target
    assert capped.approved_target_contracts == 2
    assert blocked.approved_target_contracts == blocked.current_contracts == 1
    assert forced.approved_target_contracts == 0

    _raises(ValueError, lambda: RiskDecision(target, 1, "force-flat", "halted", 1))
    _raises(ValueError, lambda: RiskDecision(target, 0, "block", "halted", 1))
    _raises(ValueError, lambda: RiskDecision(target, 3, "cap", "unchanged", 1))
    _raises(ValueError, lambda: RiskDecision(target, -1, "cap", "reversed", 1))
    _raises(ValueError, lambda: RiskDecision(target, 1, "unknown", "bad", 1))
    _raises(ValueError, lambda: RiskDecision(target, True, "approve", "bad", 1))


def test_contracts_are_frozen() -> None:
    target = _target()
    _raises(FrozenInstanceError, lambda: setattr(target, "target_contracts", 0))
    decision = RiskDecision(target, 3, "approve", "ok", 1)
    _raises(FrozenInstanceError, lambda: setattr(decision, "action", "block"))


def test_target_rejects_ambiguous_values() -> None:
    _raises(
        ValueError,
        lambda: TargetPosition(TS.replace(tzinfo=None), 1, 0.5, "signal"),
    )
    _raises(ValueError, lambda: TargetPosition(TS, True, 0.5, "signal"))
    _raises(ValueError, lambda: TargetPosition(TS, 1, float("nan"), "signal"))
    _raises(ValueError, lambda: TargetPosition(TS, 1, 0.5, ""))
    _raises(
        ValueError,
        lambda: TargetPosition(TS, 1, 0.5, "signal", {"x": float("inf")}),
    )


if __name__ == "__main__":
    test_target_is_desired_and_decision_invariants()
    test_contracts_are_frozen()
    test_target_rejects_ambiguous_values()
    print("ok: 3 contract tests")
