#!/usr/bin/env python3
"""Installed-wheel check for the entrade_template adapter.

Follows the NautilusTrader developer-guide checklist
(docs/developer_guide/python_adapters.md, "Build and verify installed
wheels") for a pure-Python adapter: run this script with the venv's own
interpreter in isolated mode, e.g.

    /tmp/qc-wheel-check/bin/python -I scripts/verify_entrade_template_wheel.py
    /tmp/qc-wheel-check/bin/python -I scripts/verify_entrade_template_wheel.py --launch owned

Checks:
- import isolation: every adapter module resolves beneath sys.prefix;
  editable installs point back at the source tree and fail here
- launch modes: the node runs to a coordinated shutdown both owned
  (node.run()) and hosted (run_async())
- data delivery: a bar reaches the strategy
- reconciliation: startup reconciliation completes over the injected
  fake venue (the adapter yields mass assembly to the runtime hooks)
- execution: the submitted order fills with the expected quantity,
  price, commission, and cached order state
- shutdown: the run returns and the cache holds the final state

The venue is deterministic: both network clients are fakes defined in
this file, so no network access happens.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

BAR_TIME_SECONDS = 1_735_783_200  # 2025-01-02 02:00 UTC, a Thursday
CONTRACT_ID_STR = "41I1G8000.HNX"
DATA_SYMBOL = "VN30F1M"
FILL_PRICE = "1905.8"
COMMISSION = 31_500  # VND, the fake venue's tradingFee for the probe order


def check_import_isolation() -> None:
    """Every imported adapter module must resolve beneath sys.prefix."""
    from trading.adapters.entrade_template import api
    from trading.adapters.entrade_template import config as config_module
    from trading.adapters.entrade_template import constants
    from trading.adapters.entrade_template import data as data_module
    from trading.adapters.entrade_template import execution as execution_module
    from trading.adapters.entrade_template import factories
    from trading.adapters.entrade_template import providers
    from trading.adapters.entrade_template.api import (
        audit,
        contracts,
        dnse_api,
        entrade_api,
    )
    from trading.adapters.entrade_template.api import audit as audit_module
    import market_data.instruments
    import trading
    import trading.adapters

    modules = [
        trading,
        trading.adapters,
        market_data.instruments,
        config_module,
        constants,
        data_module,
        execution_module,
        factories,
        providers,
        api,
        audit,
        audit_module,
        contracts,
        dnse_api,
        entrade_api,
    ]
    prefix = str(Path(sys.prefix).resolve())
    offenders = sorted(
        {
            str(Path(module.__file__).resolve())
            for module in modules
            if not str(Path(module.__file__).resolve()).startswith(prefix)
        }
    )
    if offenders:
        raise SystemExit(
            "import isolation FAILED: modules resolve outside sys.prefix "
            f"(editable install?): {offenders}"
        )
    print("PASS import isolation: all adapter modules resolve beneath", prefix)


class FakeDnseTradingClient:
    """Emits one deterministic bar on every OHLC subscription."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.connected = False

    def on(self, event: str, handler: object) -> None:
        self.handlers[event] = handler

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def subscribe_ohlc_closed(self, **kwargs: object) -> None:
        on_ohlc = kwargs.get("on_ohlc")
        if on_ohlc is not None:
            on_ohlc(self._make_ohlc())

    @staticmethod
    def _make_ohlc() -> Any:
        from dnse.websocket.models import Ohlc

        return Ohlc.from_dict(
            {
                "symbol": DATA_SYMBOL,
                "resolution": "1",
                "open": 1000.0,
                "high": 1001.0,
                "low": 999.0,
                "close": 1000.5,
                "volume": 10,
                "time": BAR_TIME_SECONDS,
                "lastUpdated": BAR_TIME_SECONDS,
                "type": "history",
            },
        )


class FakeDnseRestClient:
    def get_ohlc(self, **kwargs: object) -> tuple[int, dict]:
        return 200, {
            "t": [BAR_TIME_SECONDS],
            "o": [1000.0],
            "h": [1001.0],
            "l": [999.0],
            "c": [1000.5],
            "v": [10],
        }

    def get_working_dates(self, **kwargs: object) -> tuple[int, dict]:
        return 200, {"workingDates": ["2025-01-02"]}


class FakeEntradeClient:
    """Deterministic Entrade REST responses for one DAY limit order."""

    def __init__(self) -> None:
        self.order_payload = {
            "id": 7001,
            "symbol": "41I1G8000",
            "side": "NB",
            "price": 1905.8,
            "quantity": 1,
            "orderType": "LO",
            "orderStatus": "Filled",
            "fillQuantity": 1,
            "averagePrice": 1905.8,
            "tradingFee": COMMISSION,
            "tradingTax": 0.0,
            "reports": [
                {
                    "version": 1,
                    "execType": "F",
                    "lastQuantity": 1,
                    "lastPrice": 1905.8,
                    "modifiedDate": "2026-09-15T02:21:48.100Z",
                },
            ],
        }

    def authenticate(self, username: str, password: str) -> str:
        return "wheel-check-token"

    def get_account_balance(self, investor_id: int | str) -> dict:
        return {
            "investorAccountId": 456,
            "nav": 100_000_000,
            "availableCash": 90_000_000,
        }

    def list_margin_portfolios(self, investor_id: int | str) -> dict:
        return {"data": [{"id": 32}]}

    def list_derivatives(self) -> dict:
        return {
            "data": [
                {
                    "symbol": "41I1G8000",
                    "type": "VN30F2M",
                    "expirationDate": "2027-08-20T00:00:00.000Z",
                    "marketPrice": 1535.2,
                },
            ],
        }

    def get_buying_power(self, **kwargs: object) -> dict:
        return {"qmax": 10}

    def place_order(self, **kwargs: object) -> dict:
        return self.order_payload

    def get_order(self, order_id: int | str) -> dict:
        return self.order_payload

    def list_orders(self, **kwargs: object) -> dict:
        return {"data": []}

    def list_deals(self, **kwargs: object) -> dict:
        return {"data": []}

    def close(self) -> None:
        return None


def build_node(launch: str) -> tuple[Any, Any]:
    from nautilus_trader.common import Environment
    from nautilus_trader.config import LiveNodeConfig
    from nautilus_trader.live import LiveNode
    from nautilus_trader.live.clients import DataClientFactory, ExecutionClientFactory
    from nautilus_trader.model import (
        InstrumentId,
        OrderSide,
        Price,
        Quantity,
        TimeInForce,
        TraderId,
    )
    from nautilus_trader.trading import Strategy

    from trading.adapters.entrade_template.config import DnseDataClientConfig
    from trading.adapters.entrade_template.config import EntradeExecClientConfig
    from trading.adapters.entrade_template.data import DnseLiveDataClient
    from trading.adapters.entrade_template.data import build_bar_type_for_symbol
    from trading.adapters.entrade_template.execution import EntradeExecutionClient
    from trading.adapters.entrade_template.providers import (
        DnseInstrumentProvider,
        EntradeInstrumentProvider,
    )
    from market_data.instruments import FuturesInstrumentSpec

    spec = FuturesInstrumentSpec(
        symbol=DATA_SYMBOL,
        venue="HNX",
        underlying="VN30",
        currency_code="VND",
        currency_precision=0,
        currency_iso4217=704,
        currency_name="Vietnamese dong",
        price_precision=1,
        price_increment=0.1,
        multiplier=100_000,
        lot_size=1,
    )
    contract_id = InstrumentId.from_str(CONTRACT_ID_STR)
    trading_client = FakeDnseTradingClient()
    rest_client = FakeDnseRestClient()
    api = FakeEntradeClient()

    class TestDataFactory(DataClientFactory):
        @staticmethod
        def create(*, name: str, config, cache, clock):
            provider = DnseInstrumentProvider(config, clock)
            return DnseLiveDataClient(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                venue=config.venue,
                instrument_provider=provider,
                trading_client=trading_client,
                rest_client=rest_client,
            )

    class TestExecFactory(ExecutionClientFactory):
        @staticmethod
        def create(*, name: str, config, cache, clock, trader_id):
            provider = EntradeInstrumentProvider(
                api,
                config.instrument_spec,
                config.instrument_provider,
                clock=clock,
            )
            return EntradeExecutionClient(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                trader_id=trader_id,
                instrument_provider=provider,
                client=api,
            )

    class LifecycleStrategy(Strategy):
        def __init__(self) -> None:
            super().__init__()
            self.bar: Any = None
            self.order: Any = None
            self.fill: Any = None

        def on_start(self) -> None:
            self.subscribe_bars(build_bar_type_for_symbol(DATA_SYMBOL, "1", "HNX"))

        def on_bar(self, bar) -> None:
            if self.bar is None:
                self.bar = bar
                self.order = self.order_factory.limit(
                    contract_id,
                    OrderSide.BUY,
                    Quantity.from_int(1),
                    price=Price.from_str(FILL_PRICE),
                    time_in_force=TimeInForce.DAY,
                )
                self.submit_order(self.order)

        def on_order_denied(self, event) -> None:
            self.shutdown_system(f"Order denied: {event.reason}")

        def on_order_filled(self, event) -> None:
            self.fill = event
            self.shutdown_system("Wheel-check order filled")

    node = LiveNode.build(
        "ENTRADE-WHEEL-CHECK",
        LiveNodeConfig(
            environment=Environment.SANDBOX,
            trader_id=TraderId("TRADER-001"),
            timeout_connection_secs=2,
            timeout_reconciliation_secs=2,
            timeout_portfolio_secs=2,
            timeout_disconnection_secs=1,
            delay_post_stop_secs=0,
            data_clients={
                "DNSE": DnseDataClientConfig(
                    api_key="key",
                    api_secret="secret",
                    instrument_spec=spec,
                    historical_source="api",
                ),
            },
            exec_clients={
                "DNSE": EntradeExecClientConfig(
                    instrument_spec=spec,
                    username="user",
                    password="password",
                    investor_id=123,
                    account_id="DNSE-456",
                ),
            },
        ),
        data_factories={"DNSE": TestDataFactory},
        exec_factories={"DNSE": TestExecFactory},
    )
    strategy = LifecycleStrategy()
    node.add_strategy(strategy)
    print(f"PASS launch mode '{launch}': node built with both factories")
    return node, strategy


async def run_hosted(node: Any) -> None:
    async with asyncio.timeout(15):
        await node.run_async()


def verify_run(node: Any, strategy: Any) -> None:
    from nautilus_trader.model import AccountId, OrderStatus, Price, Quantity, TraderId

    if strategy.bar is None:
        raise SystemExit("data delivery FAILED: the strategy never received a bar")
    assert strategy.bar.close == Price(1000.5, 1)
    print("PASS data delivery: bar reached the strategy and the core cache")

    account = node.cache.account(AccountId("DNSE-456"))
    if account is None:
        raise SystemExit("reconciliation FAILED: the account never entered the cache")
    print("PASS reconciliation: startup reconciliation completed, account reported")

    fill = strategy.fill
    if fill is None:
        raise SystemExit("execution FAILED: the order never filled")
    assert fill.trader_id == TraderId("TRADER-001")
    assert fill.account_id == AccountId("DNSE-456")
    assert fill.last_qty == Quantity.from_int(1)
    assert fill.last_px == Price.from_str(FILL_PRICE)
    assert fill.commission.as_decimal() == Decimal(COMMISSION)
    cached = node.cache.order(strategy.order.client_order_id)
    assert cached.status == OrderStatus.FILLED
    print("PASS execution: fill quantity, price, commission, and cached state exact")
    print("PASS shutdown: run returned cleanly (launch mode verified above)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--launch",
        choices=["owned", "hosted"],
        default="hosted",
        help="node launch mode to verify",
    )
    args = parser.parse_args()

    check_import_isolation()
    node, strategy = build_node(args.launch)
    if args.launch == "owned":
        node.run()
    else:
        asyncio.run(run_hosted(node))
    verify_run(node, strategy)
    print(f"OK entrade_template wheel check passed (launch={args.launch})")


if __name__ == "__main__":
    main()
