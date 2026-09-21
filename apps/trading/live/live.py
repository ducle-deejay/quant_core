from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from nautilus_trader.common import Environment
from nautilus_trader.config import LoggerConfig
from nautilus_trader.common import LogLevel
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId

from nautilus_bridge.adapters.entrade.api.contracts import resolve_active_contract
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeAccount
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeClient
from nautilus_bridge.adapters.entrade.api.entrade_api import EntradeClientConfig
from nautilus_bridge.adapters.entrade.api.entrade_api import investor_id_from_token
from nautilus_bridge.adapters.entrade.config import DnseDataClientConfig
from nautilus_bridge.adapters.entrade.config import EntradeExecClientConfig
from nautilus_bridge.adapters.entrade.factories import DnseLiveDataClientFactory
from nautilus_bridge.adapters.entrade.factories import EntradeLiveExecClientFactory
from nautilus_bridge.instruments.instruments import load_futures_instrument_spec

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "trading"))

from actors.ema_cross_actor import EMACrossActor  # noqa: E402
from actors.ema_cross_actor import EMACrossActorConfig  # noqa: E402
from strategies.ema_cross_strategy import EMACrossStrategy  # noqa: E402
from strategies.ema_cross_strategy import EMACrossStrategyConfig  # noqa: E402

load_dotenv(ROOT / ".env", override=True)

NAME = "QUANTCORE-LIVE-001"
TRADER_ID = TraderId.from_str("QUANTCORE-001")
ENTRADE_ACCOUNT = EntradeAccount.DEMO
SPEC_PATH = (
    ROOT
    / "src"
    / "nautilus_bridge"
    / "instruments"
    / "instrument_definitions"
    / "vn30f1m.hnx.json"
)

spec = load_futures_instrument_spec(SPEC_PATH)

client = EntradeClient(EntradeClientConfig(account=ENTRADE_ACCOUNT))
token = client.authenticate(os.environ["ENTRADE_USERNAME"], os.environ["ENTRADE_PASSWORD"])
investor_id = os.getenv("ENTRADE_INVESTOR_ID") or investor_id_from_token(token)
if investor_id is None:
    raise RuntimeError("ENTRADE_INVESTOR_ID is not set and the auth token did not contain it")
account_id = f"DNSE-{client.get_account_balance(investor_id)['investorAccountId']}"
contract = resolve_active_contract(client.list_derivatives(), logical_symbol=spec.symbol, at=datetime.now(UTC))
contract_id = spec.with_symbol(contract.symbol).instrument_id()

node = (
    LiveNode.builder(NAME, TRADER_ID, Environment.LIVE)
    .add_data_client(
        "DNSE",
        DnseLiveDataClientFactory(),
        DnseDataClientConfig(
            api_key=os.environ["API_KEY"],
            api_secret=os.environ["API_SECRET"],
            instrument_spec=spec,
            historical_source="api",
        ),
    )
    .add_exec_client(
        "DNSE",
        EntradeLiveExecClientFactory(),
        EntradeExecClientConfig(
            instrument_spec=spec,
            username=os.environ["ENTRADE_USERNAME"],
            password=os.environ["ENTRADE_PASSWORD"],
            investor_id=investor_id,
            account_id=account_id,
            account=ENTRADE_ACCOUNT,
        ),
    )
    .with_logging(LoggerConfig(stdout_level=LogLevel.INFO))
    .build()
)
node.add_actor(
    EMACrossActor(
        EMACrossActorConfig(
            instrument_id=contract_id,
        ),
    ),
)
node.add_strategy(
    EMACrossStrategy(
        EMACrossStrategyConfig(
            instrument_id=contract_id,
        ),
    ),
)

node.run()
