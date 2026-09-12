# spec: 40-tests.md E — runtime config loading (strict keys, confirm-live)

import json
from pathlib import Path

import pytest

from trading.config_loader import load_runtime

BASE = {
    "instrument": "VN30F1M",
    "capital_vnd": 100000000,
    "environment": "live",
    "broker": "entrade",
    "account": "demo",
    "close_positions_on_expiry_day": True,
}


def write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(payload))
    return path


def test_load_runtime_defaults_applied(tmp_path):
    config = load_runtime(write(tmp_path, {}))
    assert config.instrument.symbol == "VN30F1M"
    assert config.capital_vnd == 100_000_000.0
    assert config.environment == "live"
    assert config.broker == "entrade"
    assert config.account == "demo"
    assert config.close_positions_on_expiry_day is True


def test_load_runtime_parses_repo_config():
    repo_config = Path(__file__).resolve().parents[2] / "apps/trading/config/runtime.json"
    config = load_runtime(repo_config)
    assert config.instrument.symbol == "VN30F1M"
    assert config.account == "demo"


def test_unknown_key_rejected(tmp_path):
    payload = dict(BASE)
    payload["entrade_environment"] = "demo"  # removed knob must not come back
    with pytest.raises(ValueError):
        load_runtime(write(tmp_path, payload))


def test_live_account_requires_confirm(tmp_path):
    payload = dict(BASE)
    payload["account"] = "live"
    path = write(tmp_path, payload)
    with pytest.raises(ValueError, match="confirm-live-account"):
        load_runtime(path)
    config = load_runtime(path, confirm_live_account=True)
    assert config.account == "live"


def test_invalid_environment_rejected(tmp_path):
    payload = dict(BASE)
    payload["environment"] = "paper"  # not a Nautilus context
    with pytest.raises(ValueError):
        load_runtime(write(tmp_path, payload))
