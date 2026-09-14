"""Run EMACross live: DNSE market data, Entrade execution.

The node runs in the Nautilus Live environment context (real-time data,
real venue connections). The trading account defaults to the Entrade demo
(papertrade) account — virtual money, real broker matching. Set
ENTRADE_ACCOUNT to EntradeAccount.LIVE for the real-money account.

Edit the constants below to change settings; credentials come from .env
(API_KEY, API_SECRET, ENTRADE_USERNAME, ENTRADE_PASSWORD, optional
ENTRADE_INVESTOR_ID). Run from the repository root:

    .venv-v2/bin/python apps/trading/live/live.py
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from nautilus_trader.common import Environment
from nautilus_trader.config import LoggerConfig
from nautilus_trader.common import LogLevel
from nautilus_trader.live import LiveNode
from nautilus_trader.model import BarType
from nautilus_trader.model import TraderId

from trading.adapters.entrade_template.api.contracts import resolve_active_contract
from trading.adapters.entrade_template.api.entrade_api import EntradeAccount
from trading.adapters.entrade_template.api.entrade_api import EntradeClient
from trading.adapters.entrade_template.api.entrade_api import EntradeClientConfig
from trading.adapters.entrade_template.api.entrade_api import investor_id_from_token
from trading.adapters.entrade_template.config import DnseDataClientConfig
from trading.adapters.entrade_template.config import EntradeExecClientConfig
from trading.adapters.entrade_template.factories import DnseLiveDataClientFactory
from trading.adapters.entrade_template.factories import EntradeLiveExecClientFactory
from trading.instruments import load_futures_instrument_spec

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

RESOLUTION = "1"
TRADE_SIZE = Decimal("1")
FAST_EMA_PERIOD = 10
SLOW_EMA_PERIOD = 20

_spec = load_futures_instrument_spec(ROOT / "src" / "market_data" / "instrument_definitions" / "vn30f1m.hnx.json")

_client = EntradeClient(EntradeClientConfig(account=ENTRADE_ACCOUNT))
_token = _client.authenticate(os.environ["ENTRADE_USERNAME"], os.environ["ENTRADE_PASSWORD"])
_investor_id = os.getenv("ENTRADE_INVESTOR_ID") or investor_id_from_token(_token)
if _investor_id is None:
    raise RuntimeError("ENTRADE_INVESTOR_ID is not set and the auth token did not contain it")
_broker_account_id = _client.get_account_balance(_investor_id)["investorAccountId"]
ACCOUNT_ID = f"DNSE-{_broker_account_id}"
_contract = resolve_active_contract(
    _client.list_derivatives(),
    logical_symbol=_spec.symbol,
    at=datetime.now(UTC),
)
CONTRACT_INSTRUMENT_ID = _spec.with_symbol(_contract.symbol).instrument_id()
BAR_TYPE = BarType.from_str(f"{CONTRACT_INSTRUMENT_ID}-{RESOLUTION}-MINUTE-LAST-EXTERNAL")

node = (
    LiveNode.builder(NAME, TRADER_ID, Environment.LIVE)
    .add_data_client(
        "DNSE",
        DnseLiveDataClientFactory(),
        DnseDataClientConfig(
            api_key=os.environ["API_KEY"],
            api_secret=os.environ["API_SECRET"],
            instrument_spec=_spec,
            historical_source="api",
        ),
    )
    .add_exec_client(
        "DNSE",
        EntradeLiveExecClientFactory(),
        EntradeExecClientConfig(
            instrument_spec=_spec,
            username=os.environ["ENTRADE_USERNAME"],
            password=os.environ["ENTRADE_PASSWORD"],
            investor_id=_investor_id,
            account_id=ACCOUNT_ID,
            account=ENTRADE_ACCOUNT,
        ),
    )
    .with_logging(LoggerConfig(stdout_level=LogLevel.INFO))
    .build()
)

node.add_actor(
    EMACrossActor(
        EMACrossActorConfig(
            bar_type=BAR_TYPE,
            fast_ema_period=FAST_EMA_PERIOD,
            slow_ema_period=SLOW_EMA_PERIOD,
        ),
    ),
)
node.add_strategy(
    EMACrossStrategy(
        EMACrossStrategyConfig(
            instrument_id=CONTRACT_INSTRUMENT_ID,
            trade_size=TRADE_SIZE,
        ),
    ),
)

node.run()
