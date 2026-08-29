from __future__ import annotations

from nautilus_trader.config import LiveExecClientConfig

from trading.adapters.entrade.transport import EntradeEnvironment
from trading.instruments import FuturesInstrumentSpec


DNSE_EXECUTION_CLIENT_NAME = "DNSE"


class EntradeExecClientConfig(LiveExecClientConfig, frozen=True, kw_only=True):
    """Nautilus extension configuration for Entrade execution."""

    instrument_spec: FuturesInstrumentSpec
    username: str | None = None
    password: str | None = None
    investor_id: int | str | None = None
    environment: EntradeEnvironment = EntradeEnvironment.DEMO
    base_url: str = "https://services.entrade.com.vn"
    timeout_seconds: float = 30.0
