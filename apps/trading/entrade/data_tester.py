"""Stream DNSE market data with the built-in DataTester actor.

Follows the NautilusTrader per-adapter live tester convention
(examples/live/<adapter>/data_tester.py). The node connects to the DNSE
OpenAPI, subscribes to the configured instrument's quotes and bars, and logs
everything through DataTester. No orders are placed.

DNSE serves quotes per monthly contract only (the continuous symbol is
bars-only), so the tester resolves the active contract up front: bars are
subscribed on the continuous symbol and quotes on the active contract.
Both instruments are loaded into the provider.

Usage: .venv-v2/bin/python apps/trading/entrade/data_tester.py
Credentials come from .env (API_KEY, API_SECRET, ENTRADE_USERNAME,
ENTRADE_PASSWORD, optional ENTRADE_INVESTOR_ID).
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from nautilus_trader.common import Environment
from nautilus_trader.common import LogLevel
from nautilus_trader.config import LiveNodeConfig
from nautilus_trader.config import LoggerConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import BarType
from nautilus_trader.model import ClientId
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import TraderId
from nautilus_trader.testkit import DataTesterConfig

from nautilus_bridge.adapters.entrade.api.contracts import resolve_active_contract
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeAccount
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeClient
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeClientConfig
from nautilus_bridge.adapters.entrade.api.entrade_api import investor_id_from_token
from nautilus_bridge.adapters.entrade.config import DnseDataClientConfig
from nautilus_bridge.adapters.entrade.factories import DnseLiveDataClientFactory
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import CONTINUOUS_ID
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import CONTINUOUS_SYMBOL
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VENUE

ROOT = Path(__file__).resolve().parents[3]
DATA_CLIENT_NAME = "DNSE"
TRADER_ID = TraderId.from_str("TESTER-001")


def resolve_active_contract_symbol() -> str:
    """Resolve the front-month contract symbol through the Entrade API."""
    client = EntradeClient(EntradeClientConfig(account=EntradeAccount.DEMO))
    token = client.authenticate(os.environ["ENTRADE_USERNAME"], os.environ["ENTRADE_PASSWORD"])
    investor_id = os.getenv("ENTRADE_INVESTOR_ID") or investor_id_from_token(token)
    if investor_id is None:
        raise RuntimeError("ENTRADE_INVESTOR_ID is not set and the auth token did not contain it")
    derivatives = client.list_derivatives()
    contract = resolve_active_contract(
        derivatives,
        logical_symbol=CONTINUOUS_SYMBOL.value,
        at=datetime.now(UTC),
    )
    return contract.symbol


def main() -> None:
    """Run the DNSE data tester against the production DNSE OpenAPI."""
    parser = argparse.ArgumentParser(description="DNSE data connectivity tester")
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    load_dotenv(args.env, override=True)

    contract_symbol = resolve_active_contract_symbol()
    contract_instrument_id = InstrumentId.from_str(f"{contract_symbol}.{VENUE.value}")
    bar_type = BarType.from_str(f"{CONTINUOUS_ID}-1-MINUTE-LAST-EXTERNAL")
    print(f"active contract: {contract_symbol} -> {contract_instrument_id}")

    node = (
        LiveNode.builder("DNSE-DATA-TESTER-001", TRADER_ID, Environment.LIVE)
        .add_data_client(
            DATA_CLIENT_NAME,
            DnseLiveDataClientFactory(),
            DnseDataClientConfig(
                api_key=os.environ["API_KEY"],
                api_secret=os.environ["API_SECRET"],
                symbols=(CONTINUOUS_SYMBOL.value, contract_symbol),
                historical_source="api",
            ),
        )
        .build()
    )
    node.add_builtin_actor(
        "DataTester",
        DataTesterConfig(
            client_id=ClientId.from_str(DATA_CLIENT_NAME),
            instrument_ids=[contract_instrument_id],
            bar_types=[bar_type],
            subscribe_quotes=True,
            subscribe_trades=True,
            subscribe_book_depth=True,
            book_depth=10,
            subscribe_bars=True,
            request_instruments=True,
            request_bars=True,
            log_data=True,
        ),
    )

    node.run()


if __name__ == "__main__":
    main()
