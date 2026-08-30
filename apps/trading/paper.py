"""Milestone-1 paper runner: bridge strategy + risk overlay on the entrade demo.

Composes the three wiring workstreams into one Nautilus TradingNode:

    DNSE live bars (1-min) --> BridgeStrategy (alpha_core decisions)
                                  |  target -> gate -> orders (LO/MAK)
                                  v
                          entrade demo execution client
                                  ^
    RiskOverlayActor (C7): limits, loss cut, staleness, flatten retry

Usage (project venv; credentials via environment or --env file):

    ENTRADE_USERNAME=... ENTRADE_PASSWORD=... ENTRADE_INVESTOR_ID=... \\
    API_KEY=... API_SECRET=... \\
    .venv/bin/python3 apps/trading/paper.py [--env .env] [--dry-run]

--dry-run builds and prints the full runtime composition without connecting
(no credentials required, safe to run outside market hours).

Canon/decision references: STG-5, STG-6, STG-7 (frozen design), DEC-006
(cost model), DEC-008 (wiring architecture), OBS-009/OBS-010 (entrade facts).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from nautilus_trader.common.config import LoggingConfig
from nautilus_trader.config import RoutingConfig
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.config import LiveDataEngineConfig
from nautilus_trader.live.config import LiveExecEngineConfig
from nautilus_trader.live.node import TradingNode

from market_data.instrument_provider import instrument_definition_path
from market_data.instruments import load_futures_instrument_spec
from trading.adapters.dnse.config import DNSE_DATA_CLIENT_NAME
from trading.adapters.dnse.config import DnseDataClientConfig
from trading.adapters.dnse.data import build_bar_type_for_symbol
from trading.adapters.dnse.factory import DnseLiveDataClientFactory
from trading.adapters.entrade.config import DNSE_EXECUTION_CLIENT_NAME
from trading.adapters.entrade.config import EntradeExecClientConfig
from trading.adapters.entrade.factory import EntradeLiveExecClientFactory
from trading.adapters.entrade.transport import EntradeEnvironment
from market_data.notify import trading_notifier_from_env
from trading.portfolio import PortfolioOrchestrator
from trading.portfolio import default_seed_portfolio_config
from trading.risk.overlay import RiskOverlayActor
from trading.risk.overlay import RiskOverlayConfig
from trading.strategies.bridge import BridgeConfig
from trading.strategies.bridge import BridgeStrategy


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = ROOT / ".env"
INSTRUMENT_NAME = "VN30F1M"
TRADER_ID = "TRADER-001"
# Bridge id formula (v1): f"{component_id}-{order_id_tag}" -> "BridgeStrategy-bridge";
# the risk overlay subscribes to the bridge's order topic under this exact id.
BRIDGE_STRATEGY_ID = "BridgeStrategy-bridge"


def _load_credentials(env_path: Path) -> None:
    """Load .env if present; individual vars can also come from the shell."""
    if env_path.exists():
        load_dotenv(env_path, override=True)


def _require(env_var: str, dry_run: bool) -> str | None:
    value = os.getenv(env_var)
    if value is None and not dry_run:
        raise SystemExit(
            f"Missing {env_var} in environment or {DEFAULT_ENV_PATH}",
        )
    return value


def build_composition(dry_run: bool) -> TradingNode:
    """Build the milestone-1 node: data + demo execution + risk + bridge."""
    api_key = _require("API_KEY", dry_run)
    api_secret = _require("API_SECRET", dry_run)
    entrade_username = _require("ENTRADE_USERNAME", dry_run)
    entrade_password = _require("ENTRADE_PASSWORD", dry_run)
    entrade_investor_id = os.getenv("ENTRADE_INVESTOR_ID")

    instrument_spec = load_futures_instrument_spec(
        instrument_definition_path(INSTRUMENT_NAME),
    )
    bar_type = build_bar_type_for_symbol(
        symbol=instrument_spec.symbol,
        resolution="1",
        venue=instrument_spec.venue,
    )
    routing = RoutingConfig(default=True, venues=frozenset({instrument_spec.venue}))

    data_client_config = DnseDataClientConfig(
        api_key=api_key,
        api_secret=api_secret,
        instrument_spec=instrument_spec,
        routing=routing,
    )
    exec_client_config = EntradeExecClientConfig(
        instrument_spec=instrument_spec,
        username=entrade_username,
        password=entrade_password,
        investor_id=(
            int(entrade_investor_id) if entrade_investor_id is not None else None
        ),
        environment=EntradeEnvironment.DEMO,
        routing=routing,
    )

    node_config = TradingNodeConfig(
        trader_id=TRADER_ID,
        logging=LoggingConfig(log_level=os.getenv("LOG_LEVEL", "INFO"), log_colors=False),
        data_engine=LiveDataEngineConfig(validate_data_sequence=True),
        exec_engine=LiveExecEngineConfig(
            reconciliation=True,
            snapshot_positions=True,  # risk overlay seeds position from cache on start
        ),
        strategies=[],  # both strategies are added programmatically below
        data_clients={DNSE_DATA_CLIENT_NAME: data_client_config},
        exec_clients={DNSE_EXECUTION_CLIENT_NAME: exec_client_config},
    )

    node = TradingNode(config=node_config)
    node.add_data_client_factory(DNSE_DATA_CLIENT_NAME, DnseLiveDataClientFactory)
    node.add_exec_client_factory(DNSE_EXECUTION_CLIENT_NAME, EntradeLiveExecClientFactory)

    # Telegram alerting (failure-safe; None when TELEGRAM_* env unset).
    notifier = trading_notifier_from_env()

    # Workstream C: risk overlay first so the bridge can reference the instance.
    risk_config = RiskOverlayConfig(
        bar_type=bar_type,
        bridge_strategy_id=BRIDGE_STRATEGY_ID,
        order_id_tag="risk",
    )
    risk_actor = RiskOverlayActor(config=risk_config, notifier=notifier)

    # Workstream A: portfolio orchestrator (pure alpha_core decisions).
    portfolio = PortfolioOrchestrator(config=default_seed_portfolio_config())

    # Workstream B: bridge strategy, constructed directly (BridgeConfig is a
    # plain dataclass; Nautilus ImportableStrategyConfig cannot round-trip it).
    bridge = BridgeStrategy(
        BridgeConfig(
            instrument_id=str(bar_type.instrument_id),
            bar_type=str(bar_type),
            portfolio=portfolio,
            risk=risk_actor,
            notifier=notifier,
        ),
    )

    node.trader.add_strategy(risk_actor)
    node.trader.add_strategy(bridge)
    return node


def main() -> None:
    parser = argparse.ArgumentParser(description="Milestone-1 paper runner (entrade demo)")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--dry-run", action="store_true", help="build + print composition, do not connect")
    args = parser.parse_args()

    _load_credentials(args.env)
    node = build_composition(dry_run=args.dry_run)

    if args.dry_run:
        print("DRY RUN: composition built successfully")
        print(f"  instrument : {INSTRUMENT_NAME} (5% entrade margin, DEMO env)")
        print("  strategies : RiskOverlayActor, BridgeStrategy")
        print("  data       : DNSE live 1-min bars (warmup then live)")
        print("  execution  : entrade demo (LO/MAK), reconciliation on")
        return

    node.build()
    try:
        node.run()
    except KeyboardInterrupt:
        print("\nStopped by operator")
    finally:
        node.dispose()


if __name__ == "__main__":
    sys.exit(main())
