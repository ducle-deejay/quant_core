"""Exercise the Entrade demo execution path with the built-in ExecTester.

Follows the NautilusTrader per-adapter live tester convention
(examples/live/<adapter>/exec_tester.py). The node runs real DNSE market
data and the real Entrade execution client trading the demo (papertrade)
account, so every order lives on virtual money. The node itself runs in the
Nautilus Live environment context either way.

A pre-flight step authenticates with the credentials in .env, resolves the
active VN30F monthly contract, and derives the Nautilus account id
("DNSE-<investorAccountId>") required by the exec client config.

Two modes:

- default: the builtin ExecTester with the full flag set — aggressive DAY
  limit quotes on both sides (LO buy + sell), TOB-offset maintenance that
  exercises the modify path, an MOK (market FOK) opening position, cancel
  and MAK close on stop. Runs until Ctrl+C.
- --sweep: a one-shot sequential strategy covering the commands the builtin
  never sends — MTL (market-to-limit) entry, MOK entry, MAK flatten,
  CancelAllOrders sweep, QueryAccount — then shuts the node down. One run
  completes in well under a minute during a trading session.

Upgrade workflow: re-run both modes to exercise the full adapter
surface.

Usage:
    uv run python apps/trading/entrade_template/exec_tester.py                 # dry run: commands are built but not sent
    uv run python apps/trading/entrade_template/exec_tester.py --live-orders   # submit real (demo) orders
    uv run python apps/trading/entrade_template/exec_tester.py --live-orders --sweep
Env: API_KEY, API_SECRET, ENTRADE_USERNAME, ENTRADE_PASSWORD, optional ENTRADE_INVESTOR_ID.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from nautilus_trader.common import Environment
from nautilus_trader.common import LogLevel
from nautilus_trader.config import LiveNodeConfig
from nautilus_trader.config import LoggerConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import AccountId
from nautilus_trader.model import ClientId
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import OrderSide
from nautilus_trader.model import Quantity
from nautilus_trader.model import StrategyId
from nautilus_trader.model import TimeInForce
from nautilus_trader.model import TraderId
from nautilus_trader.testkit import ExecTesterConfig
from nautilus_trader.trading import Strategy

from trading.adapters.entrade_template.api.entrade_api import EntradeClient
from trading.adapters.entrade_template.api.entrade_api import EntradeClientConfig
from trading.adapters.entrade_template.api.entrade_api import EntradeAccount
from trading.adapters.entrade_template.api.entrade_api import investor_id_from_token
from trading.adapters.entrade_template.api.contracts import resolve_active_contract
from trading.adapters.entrade_template.config import DnseDataClientConfig
from trading.adapters.entrade_template.config import EntradeExecClientConfig
from trading.adapters.entrade_template.factories import DnseLiveDataClientFactory
from trading.adapters.entrade_template.factories import EntradeLiveExecClientFactory
from trading.instruments import load_futures_instrument_spec

ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "src" / "market_data" / "instrument_definitions" / "vn30f1m.hnx.json"
CLIENT_NAME = "DNSE"
TRADER_ID = TraderId.from_str("TESTER-001")
ORDER_QTY = "1"


def resolve_demo_context(spec) -> tuple[str, object]:
    """Authenticate and resolve the account id and active contract instrument."""
    import os

    username = os.environ["ENTRADE_USERNAME"]
    password = os.environ["ENTRADE_PASSWORD"]
    investor_id = os.getenv("ENTRADE_INVESTOR_ID")

    client = EntradeClient(EntradeClientConfig(account=EntradeAccount.DEMO))
    token = client.authenticate(username, password)
    investor_id = investor_id or investor_id_from_token(token)
    if investor_id is None:
        raise RuntimeError(
            "ENTRADE_INVESTOR_ID is not set and the auth token did not contain it; "
            "run apps/trading/check_auth.py to obtain it",
        )

    balance = client.get_account_balance(investor_id)
    broker_account_id = balance["investorAccountId"]
    account_id = f"{CLIENT_NAME}-{broker_account_id}"

    derivatives = client.list_derivatives()
    contract = resolve_active_contract(
        derivatives,
        logical_symbol=spec.symbol,
        at=datetime.now(UTC),
    )
    contract_instrument_id = spec.with_symbol(contract.symbol).instrument_id()
    print(f"active contract: {contract.symbol} -> {contract_instrument_id}")
    print(f"nautilus account id: {account_id}")
    return account_id, contract_instrument_id


class CapabilitySweepStrategy(Strategy):
    """One-shot sweep of the commands the builtin ExecTester never sends.

    Sequence: MTL buy -> MOK buy -> MAK flatten -> CancelAllOrders ->
    QueryAccount -> shutdown. Each step advances on the first resolution
    event; a resting MTL is canceled by a watchdog timer. on_stop cancels
    any stray order and flattens any residual position with MAK.
    """

    def __init__(self) -> None:
        super().__init__()
        self._contract_id: InstrumentId | None = None
        self._account_id: AccountId | None = None
        self._dry_run = True
        self._step = 0  # 0=MTL 1=MOK 2=flatten 3=done
        self._pending = False
        self._position = 0
        self._events: list[str] = []
        self._mtl_order = None

    def configure(
        self,
        contract_id: InstrumentId,
        account_id: str,
        *,
        dry_run: bool,
    ) -> None:
        # The PyO3 Strategy.__new__ accepts at most one positional argument,
        # so subclasses take no constructor arguments.
        self._contract_id = contract_id
        self._account_id = AccountId.from_str(account_id)
        self._dry_run = dry_run

    def on_start(self) -> None:
        if self._dry_run:
            print("SWEEP dry run: re-run with --live-orders during a session")
            self.shutdown_system("sweep skipped in dry run")
            return
        # Marketable orders need a cached quote or the risk engine denies
        # them with MARKET_PRICE_UNAVAILABLE before they reach the broker.
        self.subscribe_quotes(self._contract_id)

    def on_quote_tick(self, tick) -> None:
        if self._step != 0:
            return
        self._pending = True
        self._mtl_order = self.order_factory.market_to_limit(
            self._contract_id, OrderSide.BUY, Quantity.from_str(ORDER_QTY),
        )
        self.submit_order(self._mtl_order)
        self.clock.set_timer(
            "sweep-mtl-watch",
            timedelta(seconds=10),
            callback=self._on_mtl_watch,
        )

    def _on_mtl_watch(self, event) -> None:
        if (
            self._step == 0
            and self._pending
            and self._mtl_order is not None
            and self._mtl_order.is_open
        ):
            self.cancel_order(self._mtl_order.client_order_id)

    def _advance(self) -> None:
        if self._step == 0:
            self._step = 1
            print(f"SWEEP mtl resolved position={self._position}")
            self._pending = True
            self.submit_order(self.order_factory.market(
                self._contract_id, OrderSide.BUY, Quantity.from_str(ORDER_QTY),
                time_in_force=TimeInForce.FOK,
            ))
        elif self._step == 1:
            self._step = 2
            print(f"SWEEP mok resolved position={self._position}")
            if self._position != 0:
                self._pending = True
                self.submit_order(self.order_factory.market(
                    self._contract_id,
                    OrderSide.SELL if self._position > 0 else OrderSide.BUY,
                    Quantity.from_str(str(abs(self._position))),
                    time_in_force=TimeInForce.IOC,
                ))
            else:
                self._advance()
        elif self._step == 2:
            self._step = 3
            print(f"SWEEP flatten done position={self._position}")
            self.cancel_all_orders(self._contract_id)
            self.query_account(self._account_id, client_id=ClientId(CLIENT_NAME))
            self.shutdown_system("capability sweep complete")

    def on_order_filled(self, event) -> None:
        side = 1 if event.order_side == OrderSide.BUY else -1
        self._position += side * int(event.last_qty.as_decimal())
        self._events.append(
            f"FILL qty={event.last_qty} px={event.last_px} commission={event.commission}",
        )
        if self._pending:
            self._pending = False
            self._advance()

    def on_order_canceled(self, event) -> None:
        self._events.append(f"CANCELED {event.client_order_id}")
        if self._pending:
            self._pending = False
            self._advance()

    def on_order_rejected(self, event) -> None:
        self._events.append(f"REJECTED {event.client_order_id} reason={event.reason}")
        if self._pending:
            self._pending = False
            self._advance()

    def on_order_denied(self, event) -> None:
        self._events.append(f"DENIED {event.client_order_id} reason={event.reason}")
        if self._pending:
            self._pending = False
            self._advance()

    def on_stop(self) -> None:
        self.cancel_all_orders(self._contract_id)
        if self._position != 0:
            self.submit_order(self.order_factory.market(
                self._contract_id,
                OrderSide.SELL if self._position > 0 else OrderSide.BUY,
                Quantity.from_str(str(abs(self._position))),
                time_in_force=TimeInForce.IOC,
            ))
        for line in self._events:
            print(line)
        print(f"SWEEP final position={self._position}")


def main() -> None:
    """Run the Entrade demo execution tester."""
    parser = argparse.ArgumentParser(description="Entrade demo execution tester")
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--live-orders",
        action="store_true",
        help="submit real orders on the demo account (default: dry run)",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="one-shot MTL/MOK/CancelAll/QueryAccount sweep instead of the builtin loop",
    )
    args = parser.parse_args()
    load_dotenv(args.env, override=True)

    import os

    spec = load_futures_instrument_spec(SPEC_PATH)
    account_id, contract_instrument_id = resolve_demo_context(spec)

    node = (
        LiveNode.builder("ENTRADE-EXEC-TESTER-001", TRADER_ID, Environment.LIVE)
        .add_data_client(
            CLIENT_NAME,
            DnseLiveDataClientFactory(),
            DnseDataClientConfig(
                api_key=os.environ["API_KEY"],
                api_secret=os.environ["API_SECRET"],
                instrument_spec=spec,
                historical_source="api",
            ),
        )
        .add_exec_client(
            CLIENT_NAME,
            EntradeLiveExecClientFactory(),
            EntradeExecClientConfig(
                instrument_spec=spec,
                username=os.environ["ENTRADE_USERNAME"],
                password=os.environ["ENTRADE_PASSWORD"],
                investor_id=os.getenv("ENTRADE_INVESTOR_ID"),
                account_id=account_id,
                account=EntradeAccount.DEMO,
            ),
        )
        .build()
    )
    if args.sweep:
        strategy = CapabilitySweepStrategy()
        strategy.configure(
            contract_instrument_id,
            account_id,
            dry_run=not args.live_orders,
        )
        node.add_strategy(strategy)
    else:
        node.add_builtin_strategy(
            "ExecTester",
            ExecTesterConfig(
                strategy_id=StrategyId.from_str("EXEC_TESTER-001"),
                instrument_id=contract_instrument_id,
                client_id=ClientId.from_str(CLIENT_NAME),
                order_qty=Quantity.from_str(ORDER_QTY),
                subscribe_quotes=True,
                subscribe_trades=True,
                enable_limit_buys=True,
                enable_limit_sells=True,
                tob_offset_ticks=1,
                limit_time_in_force=TimeInForce.DAY,
                limit_aggressive=True,
                modify_orders_to_maintain_tob_offset=True,
                open_position_on_start_qty=Decimal(ORDER_QTY),
                open_position_on_first_quote=True,
                open_position_time_in_force=TimeInForce.FOK,
                cancel_orders_on_stop=True,
                close_positions_on_stop=True,
                close_positions_time_in_force=TimeInForce.IOC,
                dry_run=not args.live_orders,
                log_data=False,
            ),
        )

    node.run()


if __name__ == "__main__":
    main()
