"""Runtime configuration loading for the live trading runner."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from core import Account
from core import AccountLimits
from core import Instrument

#: Documented defaults applied when a key is absent from the JSON file.
DEFAULTS: dict[str, object] = {
    "instrument": "VN30F1M",
    "capital_vnd": 100_000_000.0,
    "environment": "live",
    "broker": "entrade",
    "account": "demo",
    "close_positions_on_expiry_day": True,
}

#: Allowed environment values (see ``trading.node``: only sandbox and live
#: compose; "backtest" is rejected there with NotImplementedError).
ENVIRONMENTS: tuple[str, ...] = ("backtest", "sandbox", "live")


@dataclass(frozen=True)
class RuntimeConfig:
    """Runtime selection for one live trading session.

    Parameters
    ----------
    instrument : Instrument
        Core instrument definition (symbol, venue, multiplier, tick size).
    capital_vnd : float
        Account capital in VND feeding the sizing limits.
    environment : str
        ``"backtest" | "sandbox" | "live"``; the runner only supports
        ``"sandbox"`` and ``"live"``.
    broker : str
        Broker adapter key (registry in ``trading.node``).
    account : Account
        Broker account boundary: ``Account.DEMO`` or ``Account.LIVE``.
    close_positions_on_expiry_day : bool
        Master switch for the bridge's expiry gate (force-flat at the
        expiry cutoff, reduce-only before it).
    """

    instrument: Instrument
    capital_vnd: float
    environment: str
    broker: str
    account: Account
    close_positions_on_expiry_day: bool

    def limits(self) -> AccountLimits:
        """The account limits implied by ``capital_vnd`` (core defaults otherwise)."""
        return AccountLimits(capital_vnd=self.capital_vnd)

    def summary(self) -> str:
        """One-line human-readable config summary for logs and alerts."""
        return (
            f"{self.instrument.symbol} capital={self.capital_vnd:.0f}VND "
            f"env={self.environment} broker={self.broker} "
            f"account={self.account.value} "
            f"expiry_close={'on' if self.close_positions_on_expiry_day else 'off'}"
        )


def load_runtime(path: Path, *, confirm_live_account: bool = False) -> RuntimeConfig:
    """Load and validate the runner JSON config at ``path``.

    Parameters
    ----------
    path : Path
        Path to ``runtime.json``.
    confirm_live_account : bool
        Operator confirmation required when the config selects
        ``account = "live"``.

    Returns
    -------
    RuntimeConfig
        The frozen runtime configuration.

    Raises
    ------
    ValueError
        When the file is not a JSON object, contains unknown keys, has
        wrongly typed/out-of-range values, or selects ``account = "live"``
        without ``confirm_live_account``.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"runtime config {path} must be a JSON object")

    unknown = sorted(set(payload) - set(DEFAULTS))
    if unknown:
        raise ValueError(
            f"unknown runtime config keys {unknown}; allowed keys: {sorted(DEFAULTS)}"
        )
    merged = {**DEFAULTS, **payload}

    instrument_symbol = _require_str(merged, "instrument")
    try:
        instrument = Instrument.load(instrument_symbol)
    except Exception as error:
        raise ValueError(f"unknown instrument {instrument_symbol!r}: {error}") from error

    capital_vnd = merged["capital_vnd"]
    if isinstance(capital_vnd, bool) or not isinstance(capital_vnd, (int, float)):
        raise ValueError("capital_vnd must be a number (VND)")
    if not math.isfinite(float(capital_vnd)) or float(capital_vnd) <= 0.0:
        raise ValueError("capital_vnd must be a positive finite number")
    # Build the implied account limits at load time so the sizing values the
    # runner will use are validated here (capital feeds the conversion).
    _limits = AccountLimits(capital_vnd=float(capital_vnd))

    environment = _require_str(merged, "environment")
    if environment not in ENVIRONMENTS:
        raise ValueError(
            f"environment must be one of {list(ENVIRONMENTS)}, got {environment!r}"
        )

    broker = _require_str(merged, "broker")

    account_value = _require_str(merged, "account")
    try:
        account = Account(account_value)
    except ValueError as error:
        raise ValueError(
            f"account must be one of {[member.value for member in Account]}, "
            f"got {account_value!r}"
        ) from error
    if account == Account.LIVE and not confirm_live_account:
        raise ValueError("account=live requires --confirm-live-account")

    expiry_close = merged["close_positions_on_expiry_day"]
    if not isinstance(expiry_close, bool):
        raise ValueError("close_positions_on_expiry_day must be a boolean")

    return RuntimeConfig(
        instrument=instrument,
        capital_vnd=float(capital_vnd),
        environment=environment,
        broker=broker,
        account=account,
        close_positions_on_expiry_day=expiry_close,
    )


def _require_str(values: dict, key: str) -> str:
    """Return ``values[key]`` as a non-empty stripped string."""
    value = values[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()
