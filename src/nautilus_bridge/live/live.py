"""Run the VN30F1M directional system live: DNSE market data, Entrade execution.

The node is run by ``runner.run_node``, whose exit codes are described in runner.py; a
failure while building the node raises, which also exits with a non-zero code.

Usage: uv run python -m nautilus_bridge.live.live
Env (.env at the repository root): API_KEY, API_SECRET, ENTRADE_USERNAME,
ENTRADE_PASSWORD, optional ENTRADE_INVESTOR_ID.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

from nautilus_trader.common import Environment
from nautilus_trader.common import LogLevel
from nautilus_trader.config import FileWriterConfig
from nautilus_trader.config import LoggerConfig
from nautilus_trader.live import LiveDataEngineConfig
from nautilus_trader.live import LiveExecutionEngineConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.live import LiveNodeBuilder
from nautilus_trader.live import LiveNodeConfig
from nautilus_trader.live import QueueMonitorConfig
from nautilus_trader.model import BarType
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import StrategyId
from nautilus_trader.model import TraderId

from nautilus_bridge.actors.data_monitor import DataMonitorActor
from nautilus_bridge.actors.data_monitor import DataMonitorActorConfig
from nautilus_bridge.actors.directional_alpha import DirectionalAlphaActor
from nautilus_bridge.actors.directional_alpha import DirectionalAlphaActorConfig
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeAccount
from nautilus_bridge.adapters.entrade.api.entrade_api import resolve_entrade_account_ids
from nautilus_bridge.adapters.entrade.config import DnseDataClientConfig
from nautilus_bridge.adapters.entrade.config import EntradeExecClientConfig
from nautilus_bridge.adapters.entrade.factories import DnseLiveDataClientFactory
from nautilus_bridge.adapters.entrade.factories import EntradeLiveExecClientFactory
from nautilus_bridge.strategies.directional import DirectionalStrategy
from nautilus_bridge.live.runner import run_node
from nautilus_bridge.strategies.directional import DirectionalStrategyConfig

ROOT = Path(__file__).resolve().parents[3]
LOG_DIRECTORY = ROOT / "data" / "logs" / "live"

NAME = "QUANTCORE-LIVE"
TRADER_ID = TraderId.from_str("QUANTCORE-001")
CLIENT_NAME = "DNSE"
ENTRADE_ACCOUNT = EntradeAccount.DEMO

INSTRUMENT_ID = InstrumentId.from_str("VN30F1M.HNX")
TIME_FRAME = 30
TARGET_BAR_TYPE = BarType.from_str(
    f"{INSTRUMENT_ID}-{TIME_FRAME}-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL"
)
STRATEGY_ID = StrategyId("VN30F1M-V1")


def build_node() -> LiveNode:
    load_dotenv(ROOT / ".env", override=True)
    username = os.environ["ENTRADE_USERNAME"]
    password = os.environ["ENTRADE_PASSWORD"]
    investor_id, account_id = resolve_entrade_account_ids(
        username,
        password,
        account=ENTRADE_ACCOUNT,
        client_name=CLIENT_NAME,
        investor_id=os.getenv("ENTRADE_INVESTOR_ID"),
    )

    config = LiveNodeConfig(
        environment=Environment.LIVE,
        trader_id=TRADER_ID,
        shutdown_on_error=True,
        logging=LoggerConfig(
            stdout_level=LogLevel.INFO,
            fileout_level=LogLevel.INFO,
            file_config=FileWriterConfig(directory=str(LOG_DIRECTORY)),
        ),
        # Build no time bars for intervals without updates.
        data_engine=LiveDataEngineConfig(time_bars_build_with_no_updates=False),
        # Compare cached positions with Entrade every 60 s and query fills on a mismatch
        # (docs/how_to/configure_live_trading.md, "Continuous reconciliation").
        exec_engine=LiveExecutionEngineConfig(position_check_interval_secs=60.0),
        queue_monitor=QueueMonitorConfig(
            queue_depth_trigger=1_000,
            queue_depth_clear=500,
            mean_dispatch_ns_trigger=250_000,
            mean_dispatch_ns_clear=150_000,
        ),
    )
    node = (
        LiveNodeBuilder.from_config(NAME, config)
        .add_data_client(
            CLIENT_NAME,
            DnseLiveDataClientFactory(),
            DnseDataClientConfig(
                api_key=os.environ["API_KEY"],
                api_secret=os.environ["API_SECRET"],
                historical_source="api",
            ),
        )
        .add_exec_client(
            CLIENT_NAME,
            EntradeLiveExecClientFactory(),
            EntradeExecClientConfig(
                username=username,
                password=password,
                investor_id=investor_id,
                account_id=account_id,
                account=ENTRADE_ACCOUNT,
            ),
        )
        .build()
    )

    node.add_actor(
        DataMonitorActor(
            DataMonitorActorConfig(
                instrument_id=INSTRUMENT_ID,
                bar_type=TARGET_BAR_TYPE,
                stale_after=timedelta(minutes=2),
                max_latency=timedelta(seconds=5),
            ),
        ),
    )
    node.add_actor(
        DirectionalAlphaActor(
            DirectionalAlphaActorConfig(instrument_id=INSTRUMENT_ID, bar_type=TARGET_BAR_TYPE),
        ),
    )
    node.add_strategy(
        DirectionalStrategy(
            DirectionalStrategyConfig(
                strategy_id=STRATEGY_ID,
                instrument_id=INSTRUMENT_ID,
                bar_type=TARGET_BAR_TYPE,
                manage_gtd_expiry=True,
                external_order_instrument_ids=[INSTRUMENT_ID],
            ),
        ),
    )
    return node


def main() -> int:
    node = build_node()
    try:
        return asyncio.run(run_node(node))
    finally:
        node.dispose()


if __name__ == "__main__":
    sys.exit(main())
