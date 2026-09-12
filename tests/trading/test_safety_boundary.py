# spec: safety-boundary refactor contract tests (integrator-owned)
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _fresh_import(mod: str) -> tuple[int, str, str]:
    code = f"import sys; sys.path.insert(0, r'{SRC}'); import {mod}"
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    return proc.returncode, proc.stdout, proc.stderr


# --- structure ---------------------------------------------------------------

def test_core_risk_module_removed():
    assert not (SRC / "core" / "risk.py").exists()


def test_core_package_no_longer_exports_risk_ledger():
    import core

    for name in ("RiskLedger", "ACTIVE", "HALTED", "REDUCING", "REASON_LOSS"):
        assert not hasattr(core, name), f"core still exports {name}"


def test_importing_core_risk_fails():
    code, _out, err = _fresh_import("core.risk")
    assert code != 0
    assert "ModuleNotFoundError" in err or "Error" in err


def test_trading_risk_package_removed():
    assert not (SRC / "trading" / "risk").exists()


def test_trading_portfolio_and_strategies_removed():
    assert not (SRC / "trading" / "portfolio.py").exists()
    assert not (SRC / "trading" / "strategies").exists()


def test_trading_instruments_is_shim_of_core():
    import core.instruments as core_inst
    import trading.instruments as trading_inst

    assert trading_inst.Instrument is core_inst.Instrument


def test_target_follower_strategy_removed_from_quantcore_execution():
    import quantcore.execution as exc

    assert not hasattr(exc, "TargetFollowerStrategy")


# --- strategy layer ----------------------------------------------------------

def test_strategy_package_surface():
    import nautilus_trader.trading.strategy as nt_strategy

    from strategy import (
        PortfolioOrchestrator,
        SEED_EXPRESSIONS,
        TargetPositionConfig,
        TargetPositionStrategy,
        portfolio_config_from_pool,
    )

    assert issubclass(TargetPositionStrategy, nt_strategy.Strategy)
    assert len(SEED_EXPRESSIONS) == 6
    assert callable(portfolio_config_from_pool)
    assert issubclass(TargetPositionConfig, nt_strategy.StrategyConfig)


def test_quantcore_does_not_import_trading():
    code, _out, err = _fresh_import("quantcore")
    assert code == 0, err
    proc = subprocess.run(
        [
            sys.executable, "-c",
            f"import sys; sys.path.insert(0, r'{SRC}'); import quantcore; "
            "assert 'trading' not in sys.modules, 'quantcore imported trading'",
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def test_trading_does_not_import_quantcore():
    proc = subprocess.run(
        [
            sys.executable, "-c",
            f"import sys; sys.path.insert(0, r'{SRC}'); import trading; "
            "assert 'quantcore' not in sys.modules, 'trading imported quantcore'",
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


# --- risk_limits registry + apply_policy -------------------------------------

def test_risk_limits_registry_key():
    from quantcore.risk import DEFAULT_POLICY, risk_policies

    assert DEFAULT_POLICY == "risk_limits"
    assert "risk_limits" in risk_policies.names()
    assert "trigger_matrix" not in risk_policies.names()


def test_backtest_portfolio_has_apply_policy_default_false():
    from quantcore.risk import backtest_portfolio

    sig = inspect.signature(backtest_portfolio)
    assert "apply_policy" in sig.parameters
    assert sig.parameters["apply_policy"].default is False
    assert sig.parameters["apply_policy"].kind is inspect.Parameter.KEYWORD_ONLY


def test_backtest_execution_has_strategy_factory():
    from quantcore.execution import backtest_execution

    sig = inspect.signature(backtest_execution)
    assert "strategy_factory" in sig.parameters
    assert sig.parameters["strategy_factory"].default is None


# --- safety config ------------------------------------------------------------

def test_safety_config_defaults():
    from trading.safety import SafetyConfig

    cfg = SafetyConfig()
    assert cfg.intraday_loss_limit == 0.02
    assert cfg.staleness_secs == 60.0


def test_runtime_config_parses_safety_section(tmp_path):
    from trading.config_loader import load_runtime

    payload = {
        "safety": {"intraday_loss_limit": 0.03, "staleness_secs": 45},
    }
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(payload))
    config = load_runtime(path)
    assert config.safety.intraday_loss_limit == 0.03
    assert config.safety.staleness_secs == 45.0


def test_runtime_config_safety_unknown_key_rejected(tmp_path):
    from trading.config_loader import load_runtime

    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"safety": {"stale_secs": 60}}))  # misspelled
    with pytest_raises():
        load_runtime(path)


def test_repo_runtime_json_has_safety_section():
    from trading.config_loader import load_runtime

    repo_config = REPO / "apps" / "trading" / "config" / "runtime.json"
    payload = json.loads(repo_config.read_text())
    assert payload["safety"] == {
        "intraday_loss_limit": 0.02,
        "staleness_secs": 60,
    }
    config = load_runtime(repo_config)
    assert config.safety.intraday_loss_limit == 0.02


def test_safety_section_has_no_max_contracts():
    payload = json.loads(
        (REPO / "apps" / "trading" / "config" / "runtime.json").read_text()
    )
    assert "max_contracts" not in payload["safety"]


def pytest_raises():
    import pytest

    return pytest.raises(ValueError)


# --- pure safety evaluator -----------------------------------------------------

def test_evaluate_safety_priority_loss_first():
    from trading.safety import evaluate_safety

    state, reason = evaluate_safety(
        session_open=True,
        now=_utc("2026-09-17 14:30"),
        last_bar_ts=_utc("2026-09-17 14:29"),
        staleness_secs=60.0,
        position=2,
        max_contracts=10,
        session_pnl_vnd=-2_500_000.0,  # beyond -2% of 100M
        capital_vnd=100_000_000.0,
        intraday_loss_limit=0.02,
    )
    assert state.name == "HALTED"
    assert reason == "intraday-loss-limit"


def test_evaluate_safety_stale_only_when_session_open():
    from trading.safety import evaluate_safety

    common = dict(
        now=_utc("2026-09-17 10:00"),
        last_bar_ts=_utc("2026-09-17 09:58"),
        staleness_secs=60.0,
        position=1,
        max_contracts=10,
        session_pnl_vnd=0.0,
        capital_vnd=100_000_000.0,
        intraday_loss_limit=0.02,
    )
    state, reason = evaluate_safety(session_open=True, **common)
    assert state.name == "HALTED" and reason == "stale-feed"
    state, reason = evaluate_safety(session_open=False, **common)
    assert state.name == "ACTIVE"


def test_evaluate_safety_exposure_reducing():
    from trading.safety import evaluate_safety

    state, reason = evaluate_safety(
        session_open=True,
        now=_utc("2026-09-17 10:00"),
        last_bar_ts=_utc("2026-09-17 10:00"),
        staleness_secs=60.0,
        position=12,
        max_contracts=10,
        session_pnl_vnd=0.0,
        capital_vnd=100_000_000.0,
        intraday_loss_limit=0.02,
    )
    assert state.name == "REDUCING" and reason == "exposure-cap"


def _utc(s: str):
    from datetime import datetime, timezone

    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
