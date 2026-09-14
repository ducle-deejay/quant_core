from __future__ import annotations

from typing import Any, Self

from nautilus_trader.live import ExecutionClientConfig

from trading.adapters.entrade.transport import EntradeEnvironment
from trading.instruments import FuturesInstrumentSpec

DNSE_EXECUTION_CLIENT_NAME = "DNSE"


class EntradeExecClientConfig(ExecutionClientConfig):
    """Nautilus extension configuration for Entrade execution."""

    def __new__(
        cls,
        *,
        instrument_spec: FuturesInstrumentSpec,
        username: str | None = None,
        password: str | None = None,
        investor_id: int | str | None = None,
        account_id: str,
        environment: EntradeEnvironment = EntradeEnvironment.DEMO,
        base_url: str = "https://services.entrade.com.vn",
        timeout_seconds: float = 30.0,
        instrument_provider: Any = None,
        routing: Any = None,
        **kwargs: Any,
    ) -> Self:
        del (
            instrument_spec,
            username,
            password,
            investor_id,
            account_id,
            environment,
            base_url,
            timeout_seconds,
        )
        return ExecutionClientConfig.__new__(
            cls,
            instrument_provider=instrument_provider,
            routing=routing,
            **kwargs,
        )

    def __init__(
        self,
        *,
        instrument_spec: FuturesInstrumentSpec,
        username: str | None = None,
        password: str | None = None,
        investor_id: int | str | None = None,
        account_id: str,
        environment: EntradeEnvironment = EntradeEnvironment.DEMO,
        base_url: str = "https://services.entrade.com.vn",
        timeout_seconds: float = 30.0,
        instrument_provider: Any = None,
        routing: Any = None,
        **kwargs: Any,
    ) -> None:
        del instrument_provider, routing, kwargs
        self.instrument_spec = instrument_spec
        self.username = username
        self.password = password
        self.investor_id = investor_id
        self.account_id = account_id
        self.environment = EntradeEnvironment(environment)
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
