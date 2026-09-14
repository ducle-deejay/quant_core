"""Stream DNSE market data with the built-in DataTester actor.

Follows the NautilusTrader per-adapter live tester convention
(examples/live/<adapter>/data_tester.py). The node connects to the DNSE
OpenAPI, subscribes to the configured instrument's quotes and bars, and logs
everything through DataTester. No orders are placed.

Usage: .venv-v2/bin/python apps/trading/entrade_template/data_tester.py
Credentials come from .env (API_KEY, API_SECRET).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from nautilus_trader.common import Environment
from nautilus_trader.common import LogLevel
from nautilus_trader.config import LiveNodeConfig
from nautilus_trader.config import LoggerConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import BarType
from nautilus_trader.model import ClientId
from nautilus_trader.model import TraderId
from nautilus_trader.testkit import DataTesterConfig

from trading.adapters.entrade_template.config import DnseDataClientConfig
from trading.adapters.entrade_template.factories import DnseLiveDataClientFactory
from trading.instruments import load_futures_instrument_spec

ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "src" / "market_data" / "instrument_definitions" / "vn30f1m.hnx.json"
DATA_CLIENT_NAME = "DNSE"
TRADER_ID = TraderId.from_str("TESTER-001")


def main() -> None:
    """Run the DNSE data tester against the production DNSE OpenAPI."""
    parser = argparse.ArgumentParser(description="DNSE data connectivity tester")
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    load_dotenv(args.env, override=True)

    import os

    spec = load_futures_instrument_spec(SPEC_PATH)
    instrument_id = spec.instrument_id()
    bar_type = BarType.from_str(f"{instrument_id}-1-MINUTE-LAST-EXTERNAL")

    node = (
        LiveNode.builder("DNSE-DATA-TESTER-001", TRADER_ID, Environment.LIVE)
        .add_data_client(
            DATA_CLIENT_NAME,
            DnseLiveDataClientFactory(),
            DnseDataClientConfig(
                api_key=os.environ["API_KEY"],
                api_secret=os.environ["API_SECRET"],
                instrument_spec=spec,
                historical_source="api",
            ),
        )
        .build()
    )
    node.add_builtin_actor(
        "DataTester",
        DataTesterConfig(
            client_id=ClientId.from_str(DATA_CLIENT_NAME),
            instrument_ids=[instrument_id],
            bar_types=[bar_type],
            subscribe_quotes=True,
            subscribe_bars=True,
            request_instruments=True,
            request_bars=True,
            log_data=True,
        ),
    )

    node.run()


if __name__ == "__main__":
    main()
