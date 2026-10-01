#!/usr/bin/env python3
"""Run a live node on the DNSE market data feed with only the selected components.

Every run has the DNSE data client. The Entrade execution client is added only when a
selected component places orders. The node runs until SIGINT or SIGTERM.

Usage: uv run python scripts/verify_live_component.py --with data_monitor
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from dotenv import load_dotenv

from nautilus_trader.common import DataActor
from nautilus_trader.common import Environment
from nautilus_trader.common import LogLevel
from nautilus_trader.config import FileWriterConfig
from nautilus_trader.config import LoggerConfig
from nautilus_trader.live import LiveDataEngineConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.live import LiveNodeBuilder
from nautilus_trader.live import LiveNodeConfig
from nautilus_trader.live import QueueMonitorConfig

from nautilus_bridge.actors.data_monitor import DataMonitorActor
from nautilus_bridge.actors.data_monitor import DataMonitorActorConfig
from nautilus_bridge.actors.directional_alpha import DirectionalAlphaActor
from nautilus_bridge.actors.directional_alpha import DirectionalAlphaActorConfig
from nautilus_bridge.adapters.entrade.api.entrade_api import resolve_entrade_account_ids
from nautilus_bridge.adapters.entrade.config import DnseDataClientConfig
from nautilus_bridge.adapters.entrade.config import EntradeExecClientConfig
from nautilus_bridge.adapters.entrade.factories import DnseLiveDataClientFactory
from nautilus_bridge.adapters.entrade.factories import EntradeLiveExecClientFactory
from nautilus_bridge.live.live import CLIENT_NAME
from nautilus_bridge.live.live import ENTRADE_ACCOUNT
from nautilus_bridge.live.live import INSTRUMENT_ID
from nautilus_bridge.live.live import ROOT
from nautilus_bridge.live.live import STRATEGY_ID
from nautilus_bridge.live.live import TARGET_BAR_TYPE
from nautilus_bridge.live.live import TRADER_ID
from nautilus_bridge.live.runner import run_node
from nautilus_bridge.strategies.directional import DirectionalStrategy
from nautilus_bridge.strategies.directional import DirectionalStrategyConfig

NAME = "QUANTCORE-VERIFY"
LOG_DIRECTORY = ROOT / "data" / "logs" / "verify"


class TopicLogger(DataActor):
    def __init__(self, pattern: str) -> None:
        super().__init__()
        self.pattern = pattern

    def on_start(self) -> None:
        self.subscribe_topic(self.pattern, self.on_message)

    def on_message(self, message: object) -> None:
        self.log.info(f"{self.pattern}: {message}")


def add_data_monitor(node: LiveNode) -> None:
    node.add_actor(
        DataMonitorActor(
            DataMonitorActorConfig(
                instrument_id=INSTRUMENT_ID,
                bar_type=TARGET_BAR_TYPE,
                stale_after=timedelta(seconds=10),
                max_latency=timedelta(seconds=5),
                check_interval=timedelta(seconds=2),
            ),
        ),
    )
    node.add_actor(TopicLogger("app.data_health.*"))


def add_directional_alpha(node: LiveNode) -> None:
    node.add_actor(
        DirectionalAlphaActor(
            DirectionalAlphaActorConfig(instrument_id=INSTRUMENT_ID, bar_type=TARGET_BAR_TYPE),
        ),
    )


def add_directional_strategy(node: LiveNode) -> None:
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


@dataclass(frozen=True)
class Component:
    add: Callable[[LiveNode], None]
    places_orders: bool = False


COMPONENTS = {
    "data_monitor": Component(add_data_monitor),
    "directional_alpha": Component(add_directional_alpha),
    "directional_strategy": Component(add_directional_strategy, places_orders=True),
}


def build_node(selected: list[str]) -> LiveNode:
    load_dotenv(ROOT / ".env", override=True)
    config = LiveNodeConfig(
        environment=Environment.LIVE,
        trader_id=TRADER_ID,
        logging=LoggerConfig(
            stdout_level=LogLevel.INFO,
            fileout_level=LogLevel.INFO,
            file_config=FileWriterConfig(directory=str(LOG_DIRECTORY)),
        ),
        data_engine=LiveDataEngineConfig(time_bars_build_with_no_updates=False),
        queue_monitor=QueueMonitorConfig(
            queue_depth_trigger=1_000,
            queue_depth_clear=500,
            mean_dispatch_ns_trigger=250_000,
            mean_dispatch_ns_clear=150_000,
        ),
    )
    builder = LiveNodeBuilder.from_config(NAME, config).add_data_client(
        CLIENT_NAME,
        DnseLiveDataClientFactory(),
        DnseDataClientConfig(
            api_key=os.environ["API_KEY"],
            api_secret=os.environ["API_SECRET"],
            historical_source="api",
        ),
    )
    if any(COMPONENTS[name].places_orders for name in selected):
        username = os.environ["ENTRADE_USERNAME"]
        password = os.environ["ENTRADE_PASSWORD"]
        investor_id, account_id = resolve_entrade_account_ids(
            username,
            password,
            account=ENTRADE_ACCOUNT,
            client_name=CLIENT_NAME,
            investor_id=os.getenv("ENTRADE_INVESTOR_ID"),
        )
        builder = builder.add_exec_client(
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
    node = builder.build()
    for name in selected:
        COMPONENTS[name].add(node)
    return node


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with", dest="selected", nargs="+", required=True, choices=COMPONENTS)
    args = parser.parse_args()
    node = build_node(args.selected)
    try:
        return asyncio.run(run_node(node))
    finally:
        node.dispose()


if __name__ == "__main__":
    sys.exit(main())
