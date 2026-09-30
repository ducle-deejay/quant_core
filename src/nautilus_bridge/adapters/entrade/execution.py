from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from types import NotImplementedType
from typing import Any
from typing import Protocol

from nautilus_trader.common import Logger
from nautilus_trader.core import UUID4
from nautilus_trader.live import (
    BatchCancelOrders,
    CancelAllOrders,
    CancelOrder,
    ClientCache,
    ExecutionClientConfig,
    GenerateFillReports,
    GenerateOrderStatusReport,
    GenerateOrderStatusReports,
    GeneratePositionStatusReports,
    ModifyOrder,
    QueryAccount,
    SubmitOrder,
    SubmitOrderList,
)
from nautilus_trader.live.clients import ExecutionClient
from nautilus_trader.model import (
    AccountBalance,
    AccountId,
    AccountType,
    ClientOrderId,
    Currency,
    ExecutionMassStatus,
    FillReport,
    FuturesContract,
    InstrumentId,
    LiquiditySide,
    Money,
    OmsType,
    OrderSide,
    OrderStatus,
    OrderStatusReport,
    OrderType,
    PositionSide,
    PositionStatusReport,
    Price,
    Quantity,
    StrategyId,
    TimeInForce,
    TradeId,
    TraderId,
    Venue,
    VenueOrderId,
)

from .config import EntradeExecClientConfig
from .constants import DNSE_EXECUTION_CLIENT_NAME
from .constants import NOT_IMPLEMENTED
from .api.contracts import VN_TZINFO
from .api.entrade_api import EntradeApiError
from .api.entrade_api import EntradeClient
from .api.entrade_api import EntradeClientConfig
from .api.entrade_api import investor_id_from_token
from .providers import EntradeInstrumentProvider
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VND
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import vn30f_expiry_date
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VENUE

ORDER_POLL_INTERVAL_SECONDS = 1.0
# How long an order whose submission outcome is unknown is searched for at the broker
# before it is reported as rejected.
UNRESOLVED_SUBMISSION_TIMEOUT_SECONDS = 30.0
# Clock difference allowed between this node and Entrade createdDate when matching a
# lost submission.
UNRESOLVED_SUBMISSION_CLOCK_SKEW_SECONDS = 5.0
DISCONNECT_POLL_JOIN_SECONDS = 2.0

ENTRADE_TERMINAL_STATUSES = frozenset(
    {"Canceled", "Expired", "DoneForDay", "Filled", "Rejected"},
)
# Entrade statuses on which the adapter emits OrderAccepted.
ENTRADE_ACCEPTED_STATUSES = frozenset(
    {"New", "PartiallyFilled", "Filled", "PendingCancel", "Expired", "DoneForDay"},
)
NAUTILUS_ACCEPTED_STATUSES = frozenset(
    {
        OrderStatus.ACCEPTED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.PENDING_CANCEL,
        OrderStatus.PENDING_UPDATE,
        OrderStatus.TRIGGERED,
    },
)


@dataclass
class EntradeOrderContext:
    order: Any
    venue_order_id: VenueOrderId
    reported_fills: set[str] = field(default_factory=set)
    last_status: str | None = None
    accepted: bool = False
    poll_failures: int = 0


@dataclass
class UnresolvedSubmission:
    """An order sent to Entrade whose response was lost, so it may or may not exist."""

    order: Any
    symbol: str
    side: str
    order_type: str
    quantity: int
    price: float
    ts_submitted_ns: int


class EntradeOrderDenied(Exception):
    """The order is refused before it is sent to Entrade."""


class SymbolResolver(Protocol):
    """Map between the instrument a strategy trades and the instrument sent to the venue."""

    def to_venue(self, instrument_id: InstrumentId, ts_ns: int) -> InstrumentId: ...

    def to_nautilus(self, instrument_id: InstrumentId, ts_ns: int) -> InstrumentId: ...


class IdentityResolver:
    """Trade every instrument under its own ID (no continuous symbols)."""

    def to_venue(self, instrument_id: InstrumentId, ts_ns: int) -> InstrumentId:
        return instrument_id

    def to_nautilus(self, instrument_id: InstrumentId, ts_ns: int) -> InstrumentId:
        return instrument_id


def entrade_order_parameters(order: Any) -> tuple[str, str, int, float]:
    """Translate a Nautilus order into the Entrade (HNX) side, order type, quantity and price.

    LIMIT with DAY, GTC or GTD is sent as LO; MARKET with DAY or GTC, and MARKET_TO_LIMIT,
    as MTL; MARKET with IOC as MAK and with FOK as MOK. The venue receives no expiry time,
    so a GTD expiry is not enforced by the venue. Other combinations raise ValueError.
    """
    side = "NB" if order.side == OrderSide.BUY else "NS"
    quantity_decimal = order.quantity.as_decimal()
    if quantity_decimal != quantity_decimal.to_integral_value():
        raise ValueError("Entrade derivative order quantity must be a whole number")
    quantity = int(quantity_decimal)
    order_type = order.order_type
    time_in_force = order.time_in_force

    if order_type == OrderType.LIMIT:
        if time_in_force in (TimeInForce.DAY, TimeInForce.GTC, TimeInForce.GTD):
            return side, "LO", quantity, order.price.as_double()
    elif order_type == OrderType.MARKET:
        if time_in_force in (TimeInForce.DAY, TimeInForce.GTC):
            return side, "MTL", quantity, 0.0
        if time_in_force == TimeInForce.IOC:
            return side, "MAK", quantity, 0.0
        if time_in_force == TimeInForce.FOK:
            return side, "MOK", quantity, 0.0
    elif order_type == OrderType.MARKET_TO_LIMIT:
        if time_in_force in (TimeInForce.DAY, TimeInForce.GTC):
            return side, "MTL", quantity, 0.0
    raise ValueError(
        f"{order_type.name} with {time_in_force.name} has no HNX equivalent",
    )


def entrade_order_status(value: str) -> OrderStatus:
    mapping = {
        "PendingNew": OrderStatus.SUBMITTED,
        "New": OrderStatus.ACCEPTED,
        "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
        "Filled": OrderStatus.FILLED,
        "PendingCancel": OrderStatus.PENDING_CANCEL,
        "Canceled": OrderStatus.CANCELED,
        "Expired": OrderStatus.EXPIRED,
        "DoneForDay": OrderStatus.EXPIRED,
        "Rejected": OrderStatus.REJECTED,
    }
    try:
        return mapping[value]
    except KeyError as e:
        raise ValueError(f"Unsupported Entrade order status: {value}") from e


def entrade_order_type(value: str) -> tuple[OrderType, TimeInForce]:
    mapping = {
        "LO": (OrderType.LIMIT, TimeInForce.DAY),
        "MTL": (OrderType.MARKET_TO_LIMIT, TimeInForce.DAY),
        "MAK": (OrderType.MARKET, TimeInForce.IOC),
        "MOK": (OrderType.MARKET, TimeInForce.FOK),
    }
    try:
        return mapping[value]
    except KeyError as e:
        raise ValueError(f"Unsupported Entrade order type: {value}") from e


def _timestamp_ns(value: str | None, fallback: int) -> int:
    if not value:
        return fallback
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = parsed.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (
        delta.days * 86_400 * 1_000_000_000
        + delta.seconds * 1_000_000_000
        + delta.microseconds * 1_000
    )


class EntradeExecutionClient(ExecutionClient):
    def __init__(
        self,
        *,
        name: str = DNSE_EXECUTION_CLIENT_NAME,
        config: ExecutionClientConfig,
        cache: ClientCache,
        clock: Any,
        trader_id: TraderId,
        instrument_provider: EntradeInstrumentProvider | None = None,
        client: EntradeClient | None = None,
        symbol_resolver: SymbolResolver | None = None,
    ) -> None:
        if not isinstance(config, EntradeExecClientConfig):
            raise TypeError("Expected EntradeExecClientConfig")
        super().__init__(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            trader_id=trader_id,
            venue=VENUE,
            account_id=AccountId(config.account_id),
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=VND,
            instrument_provider=instrument_provider,
        )
        self._client = client
        self._provider = instrument_provider
        self._resolver: SymbolResolver = symbol_resolver or IdentityResolver()
        self._config = config
        self._investor_id: int | str | None = config.investor_id
        self._investor_account_id: int | str | None = None
        self._margin_portfolio_id: int | None = None
        self._orders: dict[ClientOrderId, EntradeOrderContext] = {}
        self._client_order_ids: dict[VenueOrderId, ClientOrderId] = {}
        self._unresolved: list[UnresolvedSubmission] = []
        self._polling = False
        self._poll_task: asyncio.Task | None = None
        self._balance_stale = False
        self._log = Logger(type(self).__name__)

    @property
    def investor_id(self) -> int | str | None:
        return self._investor_id

    async def _connect(self) -> None:
        if not self._config.username or not self._config.password:
            raise ValueError("Entrade username and password are required")
        if self._client is None:
            self._client = EntradeClient(
                EntradeClientConfig(
                    account=self._config.account,
                    base_url=self._config.base_url,
                    timeout_seconds=self._config.timeout_seconds,
                ),
            )
        if self._provider is None:
            raise RuntimeError(
                "The Entrade execution client requires an instrument provider"
            )
        self._provider.set_client(self._client)
        token = await asyncio.to_thread(
            self._client.authenticate,
            self._config.username,
            self._config.password,
        )
        self._investor_id = self._investor_id or investor_id_from_token(token)
        if self._investor_id is None:
            raise ValueError(
                "Entrade investor ID was not provided and could not be read from the token"
            )

        balance = await asyncio.to_thread(
            self._client.get_account_balance, self._investor_id
        )
        account_id = balance.get("investorAccountId")
        if account_id is None:
            raise ValueError(
                "Entrade account balance did not contain investorAccountId"
            )
        expected_account_id = AccountId(f"{self.client_id.value}-{account_id}")
        if self.account_id != expected_account_id:
            raise ValueError(
                "Configured Entrade account ID does not match the authenticated account: "
                f"configured={self.account_id}, authenticated={expected_account_id}",
            )
        self._investor_account_id = account_id

        portfolios = await asyncio.to_thread(
            self._client.list_margin_portfolios, self._investor_id
        )
        available_portfolios = portfolios.get("data", [])
        if not available_portfolios:
            raise ValueError("Entrade account has no derivative margin portfolio")
        self._margin_portfolio_id = int(available_portfolios[0]["id"])

        await self.instrument_provider.initialize()
        for instrument in self._provider.list_all():
            self._handle_instrument(instrument)
        self._check_expiry_calendar()
        self._generate_balance(balance)

        self._polling = True
        self._poll_task = self.create_task(self._poll_orders(), name="entrade_order_poll")

    async def _disconnect(self) -> None:
        self._polling = False
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            await asyncio.wait({self._poll_task}, timeout=DISCONNECT_POLL_JOIN_SECONDS)
        if self._client is not None:
            await asyncio.to_thread(self._client.close)

    async def _query_account(self, command: QueryAccount) -> None:
        if self._investor_id is None or self._client is None:
            raise RuntimeError("Entrade execution client is not authenticated")
        balance = await asyncio.to_thread(
            self._client.get_account_balance, self._investor_id
        )
        self._generate_balance(balance)

    async def _query_order(self, command) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def _handles_order_venue(self, venue: Venue | None) -> bool:
        return super()._handles_order_venue(venue)

    def _provides_bulk_position_coverage(self, instrument_id: InstrumentId) -> bool:
        return super()._provides_bulk_position_coverage(instrument_id)

    def _calculate_commission(
        self,
        instrument: object,
        last_qty: Quantity,
        last_px: Price,
        liquidity_side: LiquiditySide,
    ) -> Money | None:
        return super()._calculate_commission(instrument, last_qty, last_px, liquidity_side)

    async def _register_external_order(
        self,
        client_order_id: ClientOrderId,
        venue_order_id: VenueOrderId | None,
        instrument_id: InstrumentId,
        strategy_id: StrategyId,
        ts_init: int,
    ) -> None:
        await super()._register_external_order(
            client_order_id,
            venue_order_id,
            instrument_id,
            strategy_id,
            ts_init,
        )
        # Reconciliation rebuilt an order this node did not submit (e.g. one still working
        # from before a restart); track it like our own so its later fills and
        # cancellation reach Nautilus.
        order = self.cache.order(client_order_id) if self.cache is not None else None
        if order is not None and order.is_open:
            self._context_for(order, venue_order_id)

    async def _on_instrument(self, instrument: object) -> None:
        return await super()._on_instrument(instrument)

    async def _batch_modify_orders(self, command) -> None:
        return await super()._batch_modify_orders(command)

    def _generate_balance(self, payload: dict[str, Any]) -> None:
        balance = entrade_account_balance(
            payload, VND
        )
        self.generate_account_state(
            balances=[balance],
            margins=[],
            reported=True,
            ts_event=self.clock.timestamp_ns(),
            info=payload,
        )

    def _order_for_client_id(self, client_order_id: ClientOrderId) -> Any | None:
        context = self._orders.get(client_order_id)
        if context is not None:
            return context.order
        if self.cache is None:
            return None
        return self.cache.order(client_order_id)

    def _context_for(
        self,
        order: Any,
        venue_order_id: VenueOrderId | None = None,
    ) -> EntradeOrderContext | None:
        """Return the tracking context of an order, creating it when the broker ID is known."""
        context = self._orders.get(order.client_order_id)
        if context is not None:
            return context
        venue_order_id = venue_order_id or order.venue_order_id
        if venue_order_id is None:
            return None
        return self._track_order(
            order,
            venue_order_id,
            accepted=order.status in NAUTILUS_ACCEPTED_STATUSES,
        )

    def _track_order(
        self,
        order: Any,
        venue_order_id: VenueOrderId,
        *,
        accepted: bool,
    ) -> EntradeOrderContext:
        context = EntradeOrderContext(order, venue_order_id, accepted=accepted)
        self._orders[order.client_order_id] = context
        self._client_order_ids[venue_order_id] = order.client_order_id
        return context

    async def _generate_order_status_report(
        self,
        command: GenerateOrderStatusReport,
    ) -> OrderStatusReport | None:
        venue_order_id = command.venue_order_id
        if venue_order_id is None and command.client_order_id is not None:
            context = self._orders.get(command.client_order_id)
            venue_order_id = context.venue_order_id if context else None
        if venue_order_id is None:
            return None
        self._require_account()
        assert self._client is not None
        payload = await asyncio.to_thread(self._client.get_order, venue_order_id.value)
        return self._order_status_report(payload)

    async def _generate_order_status_reports(
        self,
        command: GenerateOrderStatusReports,
    ) -> list[OrderStatusReport]:
        self._require_account()
        assert self._client is not None
        orders = await asyncio.to_thread(
            self._client.list_all_orders,
            investor_account_id=self._investor_account_id,
        )
        reports = []
        for order in orders:
            try:
                reports.append(self._order_status_report(order))
            except (KeyError, ValueError) as e:
                self._log.warning(
                    f"Skipping Entrade order {order.get('id')} in reconciliation: {e}",
                )
        if command.instrument_id is not None:
            reports = [
                report
                for report in reports
                if report.instrument_id == command.instrument_id
            ]
        if command.open_only:
            terminal = {
                OrderStatus.CANCELED,
                OrderStatus.EXPIRED,
                OrderStatus.FILLED,
                OrderStatus.REJECTED,
            }
            reports = [
                report for report in reports if report.order_status not in terminal
            ]
        if command.start is not None:
            reports = [report for report in reports if report.ts_last >= command.start]
        return reports

    async def _generate_fill_reports(
        self, command: GenerateFillReports
    ) -> list[FillReport]:
        self._require_account()
        assert self._client is not None
        if command.venue_order_id is not None:
            orders = [
                await asyncio.to_thread(
                    self._client.get_order, command.venue_order_id.value
                )
            ]
        else:
            orders = await asyncio.to_thread(
                self._client.list_all_orders,
                investor_account_id=self._investor_account_id,
            )
        reports = []
        for order in orders:
            try:
                reports.extend(self._fill_reports(order))
            except (KeyError, ValueError) as e:
                self._log.warning(
                    f"Skipping fills of Entrade order {order.get('id')} in reconciliation: {e}",
                )
        if command.instrument_id is not None:
            reports = [
                report
                for report in reports
                if report.instrument_id == command.instrument_id
            ]
        if command.start is not None:
            reports = [report for report in reports if report.ts_event >= command.start]
        return reports

    async def _generate_position_status_reports(
        self,
        command: GeneratePositionStatusReports,
    ) -> list[PositionStatusReport]:
        self._require_account()
        assert self._client is not None
        deals = await asyncio.to_thread(
            self._client.list_all_deals,
            investor_account_id=self._investor_account_id,
        )
        reports = self._position_status_reports(deals)
        if command.instrument_id is None:
            return reports
        return [
            report
            for report in reports
            if report.instrument_id == command.instrument_id
        ]

    async def _generate_mass_status(
        self, lookback_mins: int | None = None
    ) -> ExecutionMassStatus | NotImplementedType | None:
        self._require_account()
        assert self._client is not None
        balance = await asyncio.to_thread(
            self._client.get_account_balance, self._investor_id
        )
        self._generate_balance(balance)
        # The runtime assembles the mass from the report hooks above and
        # rejects an assembled mass whose identity does not match the client.
        return NotImplemented

    async def _submit_order(self, command: SubmitOrder) -> None:
        await self._submit_order_object(command.order)

    async def _prepare_submission(self, order: Any) -> UnresolvedSubmission:
        """Check an order before sending it; raise EntradeOrderDenied when it must not be sent."""
        if (
            self._investor_id is None
            or self._investor_account_id is None
            or self._margin_portfolio_id is None
            or self._provider is None
            or self._client is None
        ):
            raise EntradeOrderDenied("Entrade execution client is not connected")
        try:
            side, order_type, quantity, price = entrade_order_parameters(order)
        except ValueError as e:
            raise EntradeOrderDenied(str(e)) from e
        try:
            venue_instrument_id = self._resolver.to_venue(
                order.instrument_id, self.clock.timestamp_ns()
            )
        except ValueError as e:
            raise EntradeOrderDenied(str(e)) from e
        contract = self._provider.contract_for_instrument(venue_instrument_id)
        if contract is None:
            raise EntradeOrderDenied(
                f"{order.instrument_id} does not resolve to a loaded Entrade monthly contract",
            )

        # qmax is the maximum contracts Entrade's buying-power endpoint allows for this side
        # and price. Reduce-only orders skip that check so a close is never blocked by it.
        if not order.is_reduce_only:
            reference_price = price or contract.market_price or contract.basic_price
            if reference_price is None:
                raise EntradeOrderDenied(
                    f"Entrade buying-power check has no reference price for {contract.symbol}",
                )
            try:
                buying_power = await asyncio.to_thread(
                    self._client.get_buying_power,
                    investor_id=self._investor_id,
                    margin_portfolio_id=self._margin_portfolio_id,
                    symbol=contract.symbol,
                    side=side,
                    price=reference_price,
                )
                qmax = _parse_qmax(buying_power)
            except (EntradeApiError, ValueError) as e:
                raise EntradeOrderDenied(f"Entrade buying-power check failed: {e}") from e
            if quantity > qmax:
                raise EntradeOrderDenied(
                    f"Entrade buying power allows at most {qmax} {contract.symbol} "
                    f"contracts on side {side}; the order asks for {quantity}",
                )

        return UnresolvedSubmission(
            order=order,
            symbol=contract.symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            ts_submitted_ns=self.clock.timestamp_ns(),
        )

    async def _submit_order_object(self, order: Any) -> None:
        try:
            submission = await self._prepare_submission(order)
        except EntradeOrderDenied as e:
            self.generate_order_denied(order, str(e))
            return

        if order.time_in_force == TimeInForce.GTC:
            self._log.info(
                f"{order.client_order_id}: GTC is sent as a {submission.order_type} order, "
                "which HNX cancels at the end of the trading day",
            )
        self.generate_order_submitted(order)
        assert self._client is not None
        try:
            payload = await asyncio.to_thread(
                self._client.place_order,
                investor_id=self._investor_id,
                margin_portfolio_id=self._margin_portfolio_id,
                symbol=submission.symbol,
                side=submission.side,
                order_type=submission.order_type,
                quantity=submission.quantity,
                price=submission.price,
            )
        except EntradeApiError as e:
            if e.status_code is not None and e.status_code < 500:
                # An HTTP 4xx answer is treated as Entrade refusing the order.
                self.generate_order_rejected(
                    order,
                    f"Entrade rejected the order (HTTP {e.status_code}): {e.payload}",
                    self.clock.timestamp_ns(),
                    False,
                )
                return
            self._defer_unknown_submission(submission, str(e))
            return
        except Exception as e:  # noqa: BLE001 - any other failure also leaves the outcome unknown.
            self._defer_unknown_submission(submission, repr(e))
            return

        broker_order_id = payload.get("id") if isinstance(payload, dict) else None
        if broker_order_id is None:
            self._defer_unknown_submission(
                submission,
                f"Entrade response did not contain an order ID: {payload}",
            )
            return
        context = self._track_order(order, VenueOrderId(str(broker_order_id)), accepted=False)
        self._synchronize_order(payload, context)

    def _defer_unknown_submission(self, submission: UnresolvedSubmission, reason: str) -> None:
        self._log.warning(
            f"{submission.order.client_order_id}: Entrade submission outcome unknown ({reason}); "
            "searching the broker order list before reporting it",
        )
        self._unresolved.append(submission)

    async def _resolve_unresolved_submissions(self) -> None:
        if not self._unresolved or self._client is None:
            return
        try:
            broker_orders = await asyncio.to_thread(
                self._client.list_all_orders,
                investor_account_id=self._investor_account_id,
            )
        except Exception as e:  # noqa: BLE001 - retried on the next poll cycle.
            self._log.warning(f"Could not list Entrade orders to resolve submissions: {e}")
            broker_orders = None

        now = self.clock.timestamp_ns()
        still_unresolved: list[UnresolvedSubmission] = []
        for submission in self._unresolved:
            match = (
                self._find_broker_order(submission, broker_orders)
                if broker_orders is not None
                else None
            )
            if match is not None:
                self._log.info(
                    f"{submission.order.client_order_id}: found at Entrade as order {match['id']}",
                )
                context = self._track_order(
                    submission.order,
                    VenueOrderId(str(match["id"])),
                    accepted=False,
                )
                self._synchronize_order(match, context)
            elif now - submission.ts_submitted_ns > UNRESOLVED_SUBMISSION_TIMEOUT_SECONDS * 1e9:
                self.generate_order_rejected(
                    submission.order,
                    "Entrade submission failed and no matching order appeared at the broker "
                    f"within {UNRESOLVED_SUBMISSION_TIMEOUT_SECONDS:.0f}s",
                    now,
                    False,
                )
            else:
                still_unresolved.append(submission)
        self._unresolved = still_unresolved

    def _find_broker_order(
        self,
        submission: UnresolvedSubmission,
        broker_orders: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        earliest_ns = submission.ts_submitted_ns - UNRESOLVED_SUBMISSION_CLOCK_SKEW_SECONDS * 1e9
        candidates = [
            order
            for order in broker_orders
            if VenueOrderId(str(order.get("id"))) not in self._client_order_ids
            and order.get("symbol") == submission.symbol
            and order.get("side") == submission.side
            and order.get("orderType") == submission.order_type
            and _decimal(order.get("quantity")) == submission.quantity
            and (
                submission.order_type != "LO"
                or _decimal(order.get("price")) == Decimal(str(submission.price))
            )
            and _timestamp_ns(order.get("createdDate"), 0) >= earliest_ns
        ]
        return min(candidates, key=lambda order: _timestamp_ns(order.get("createdDate"), 0), default=None)

    async def _submit_order_list(self, command: SubmitOrderList) -> None:
        for client_order_id in command.order_list.client_order_ids():
            order = self.cache.order(client_order_id)
            if order is None:
                raise RuntimeError(
                    f"Order list contains an order missing from the cache: {client_order_id}",
                )
            await self._submit_order_object(order)

    async def _modify_order(self, command: ModifyOrder) -> None:
        order = self._order_for_client_id(command.client_order_id)
        if order is None:
            self._log.warning(f"Cannot modify {command.client_order_id}: order is unknown")
            return
        self.generate_order_modify_rejected(
            order,
            command.venue_order_id,
            "Entrade order modification is not supported by the current MVP adapter",
            self.clock.timestamp_ns(),
        )

    async def _cancel_order(self, command: CancelOrder) -> None:
        order = self._order_for_client_id(command.client_order_id)
        if order is None:
            self._log.warning(f"Cannot cancel {command.client_order_id}: order is unknown")
            return
        await self._cancel_one(order, command.venue_order_id)

    async def _cancel_one(self, order: Any, venue_order_id: VenueOrderId | None) -> None:
        context = self._context_for(order, venue_order_id)
        if context is None:
            self.generate_order_cancel_rejected(
                order,
                venue_order_id,
                "Entrade order ID is not known yet (submission outcome still being resolved)",
                self.clock.timestamp_ns(),
            )
            return
        try:
            assert self._client is not None
            payload = await asyncio.to_thread(
                self._client.cancel_order, context.venue_order_id.value
            )
        except Exception as e:  # noqa: BLE001 - broker errors become cancel rejections.
            self.generate_order_cancel_rejected(
                order,
                context.venue_order_id,
                f"Entrade order cancellation failed: {e}",
                self.clock.timestamp_ns(),
            )
            return
        self._synchronize_order(payload, context)

    async def _cancel_all_orders(self, command: CancelAllOrders) -> None:
        side = None if command.order_side == OrderSide.NO_ORDER_SIDE else command.order_side
        for order in self.cache.orders_open(instrument_id=command.instrument_id, side=side):
            await self._cancel_one(order, order.venue_order_id)

    async def _batch_cancel_orders(self, command: BatchCancelOrders) -> None:
        for cancel in command.cancels:
            await self._cancel_order(cancel)

    async def _poll_orders(self) -> None:
        """Keep every working order in sync with Entrade; one failed request never stops it."""
        while self._polling:
            await asyncio.sleep(ORDER_POLL_INTERVAL_SECONDS)
            await self._resolve_unresolved_submissions()
            working = [
                context
                for context in self._orders.values()
                if context.last_status not in ENTRADE_TERMINAL_STATUSES
            ]
            for context in working:
                await self._poll_one(context)
            if self._balance_stale:
                await self._refresh_balance()

    async def _poll_one(self, context: EntradeOrderContext) -> None:
        assert self._client is not None
        try:
            payload = await asyncio.to_thread(
                self._client.get_order, context.venue_order_id.value
            )
        except Exception as e:  # noqa: BLE001 - retried on the next poll cycle.
            context.poll_failures += 1
            if context.poll_failures == 1 or context.poll_failures % 30 == 0:
                self._log.warning(
                    f"Entrade order {context.venue_order_id} poll failed "
                    f"({context.poll_failures} in a row): {e}",
                )
            return
        context.poll_failures = 0
        try:
            self._synchronize_order(payload, context)
        except Exception as e:  # noqa: BLE001 - one malformed payload must not stop polling.
            self._log.error(f"Entrade order {context.venue_order_id} update failed: {e}")

    async def _refresh_balance(self) -> None:
        assert self._client is not None
        try:
            balance = await asyncio.to_thread(
                self._client.get_account_balance, self._investor_id
            )
        except Exception as e:  # noqa: BLE001 - retried on the next poll cycle.
            self._log.warning(f"Entrade balance refresh failed: {e}")
            return
        self._balance_stale = False
        self._generate_balance(balance)

    def _synchronize_order(
        self, payload: dict[str, Any], context: EntradeOrderContext
    ) -> None:
        order = context.order
        status = payload.get("orderStatus")
        fills = self._fill_reports(payload, client_order_id=order.client_order_id)
        new_fills = [
            fill for fill in fills if fill.trade_id.value not in context.reported_fills
        ]

        if not context.accepted and (status in ENTRADE_ACCEPTED_STATUSES or new_fills):
            context.accepted = True
            self.generate_order_accepted(
                order,
                context.venue_order_id,
                _timestamp_ns(payload.get("createdDate"), self.clock.timestamp_ns()),
            )

        for fill in new_fills:
            context.reported_fills.add(fill.trade_id.value)
            self.generate_order_filled(
                order,
                context.venue_order_id,
                None,
                fill.trade_id,
                fill.last_qty,
                fill.last_px,
                VND,
                fill.commission,
                fill.liquidity_side,
                fill.ts_event,
            )
            self._balance_stale = True

        if not status or status == context.last_status:
            return
        context.last_status = status
        ts_event = _timestamp_ns(payload.get("modifiedDate"), self.clock.timestamp_ns())
        if status == "Canceled":
            self.generate_order_canceled(order, context.venue_order_id, ts_event)
        elif status in ("Expired", "DoneForDay"):
            self.generate_order_expired(order, context.venue_order_id, ts_event)
        elif status == "Rejected":
            self.generate_order_rejected(
                order,
                str(payload.get("rejectReason") or "Entrade rejected the order"),
                ts_event,
                False,
            )

    def _instrument_for_payload(
        self,
        payload: dict[str, Any],
        context: EntradeOrderContext | None,
    ) -> tuple[InstrumentId, Any]:
        instrument_id = (
            context.order.instrument_id
            if context is not None
            else self._resolver.to_nautilus(
                InstrumentId.from_str(f"{payload['symbol']}.{self.venue.value}"),
                self.clock.timestamp_ns(),
            )
        )
        if self._provider is None:
            raise RuntimeError("Entrade instrument provider is not connected")
        instrument = self._provider.find(instrument_id)
        if instrument is None:
            raise ValueError(f"No instrument loaded for Entrade symbol {payload.get('symbol')}")
        return instrument_id, instrument

    def _order_status_report(self, payload: dict[str, Any]) -> OrderStatusReport:
        venue_order_id = VenueOrderId(str(payload["id"]))
        client_order_id = self._client_order_ids.get(venue_order_id)
        context = self._orders.get(client_order_id) if client_order_id else None
        instrument_id, instrument = self._instrument_for_payload(payload, context)
        if context is not None:
            order_type = context.order.order_type
            time_in_force = context.order.time_in_force
        else:
            order_type, time_in_force = entrade_order_type(payload["orderType"])
        ts_init = self.clock.timestamp_ns()
        ts_accepted = _timestamp_ns(payload.get("createdDate"), ts_init)
        price = _decimal(payload.get("price"))
        average_price = _decimal(payload.get("averagePrice"))
        return OrderStatusReport(
            account_id=self.account_id,
            instrument_id=instrument_id,
            venue_order_id=venue_order_id,
            client_order_id=client_order_id,
            order_side=OrderSide.BUY if payload["side"] == "NB" else OrderSide.SELL,
            order_type=order_type,
            time_in_force=time_in_force,
            order_status=entrade_order_status(payload["orderStatus"]),
            quantity=Quantity.from_decimal_dp(
                _decimal(payload["quantity"]), instrument.size_precision
            ),
            filled_qty=Quantity.from_decimal_dp(
                _decimal(payload.get("fillQuantity", 0)), instrument.size_precision
            ),
            price=Price.from_decimal_dp(price, instrument.price_precision)
            if price
            else None,
            avg_px=average_price if average_price else None,
            report_id=UUID4(),
            ts_accepted=ts_accepted,
            ts_last=_timestamp_ns(payload.get("modifiedDate"), ts_accepted),
            ts_init=ts_init,
        )

    def _fill_reports(
        self,
        payload: dict[str, Any],
        *,
        client_order_id: ClientOrderId | None = None,
    ) -> list[FillReport]:
        venue_order_id = VenueOrderId(str(payload["id"]))
        client_order_id = client_order_id or self._client_order_ids.get(venue_order_id)
        context = self._orders.get(client_order_id) if client_order_id else None
        instrument_id, instrument = self._instrument_for_payload(payload, context)

        fill_quantity = _decimal(payload.get("fillQuantity"))
        total_cost = _decimal(payload.get("tradingFee")) + _decimal(
            payload.get("tradingTax")
        )
        reports: list[FillReport] = []
        for index, report in enumerate(payload.get("reports", [])):
            last_quantity = _decimal(report.get("lastQuantity"))
            last_price = _decimal(report.get("lastPrice"))
            if report.get("execType") != "F" or last_quantity <= 0 or last_price <= 0:
                continue
            commission = (
                total_cost * last_quantity / fill_quantity
                if fill_quantity
                else Decimal(0)
            )
            trade_key = (
                f"{venue_order_id.value}-{report.get('version', 0)}-{index}-"
                f"{last_quantity.normalize():f}"
            )
            reports.append(
                FillReport(
                    account_id=self.account_id,
                    instrument_id=instrument_id,
                    venue_order_id=venue_order_id,
                    client_order_id=client_order_id,
                    trade_id=TradeId(trade_key),
                    order_side=OrderSide.BUY
                    if payload["side"] == "NB"
                    else OrderSide.SELL,
                    last_qty=Quantity.from_decimal_dp(
                        last_quantity, instrument.size_precision
                    ),
                    last_px=Price.from_decimal_dp(
                        last_price, instrument.price_precision
                    ),
                    commission=Money.from_decimal(
                        commission,
                        VND,
                    ),
                    liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
                    avg_px=_decimal(payload.get("averagePrice"))
                    if payload.get("averagePrice")
                    else None,
                    report_id=UUID4(),
                    ts_event=_timestamp_ns(
                        report.get("modifiedDate"), self.clock.timestamp_ns()
                    ),
                    ts_init=self.clock.timestamp_ns(),
                ),
            )
        return reports

    def _position_status_reports(
        self,
        deals: list[dict[str, Any]],
    ) -> list[PositionStatusReport]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for deal in deals:
            open_quantity = _decimal(deal.get("openQuantity"))
            if deal.get("status") != "ACTIVE" or open_quantity <= 0:
                continue
            if deal.get("side") not in ("NB", "NS"):
                self._log.warning(
                    f"Skipping Entrade deal {deal.get('id')} with unknown side {deal.get('side')}",
                )
                continue
            grouped.setdefault(str(deal["symbol"]), []).append(deal)

        reports: list[PositionStatusReport] = []
        for symbol, open_deals in grouped.items():
            instrument_id = self._resolver.to_nautilus(
                InstrumentId.from_str(f"{symbol}.{self.venue.value}"),
                self.clock.timestamp_ns(),
            )
            if self._provider is None:
                raise RuntimeError("Entrade instrument provider is not connected")
            instrument = self._provider.find(instrument_id)
            if instrument is None:
                self._log.warning(f"Skipping Entrade position in unloaded symbol {symbol}")
                continue

            long_deals = [deal for deal in open_deals if deal["side"] == "NB"]
            short_deals = [deal for deal in open_deals if deal["side"] == "NS"]
            if long_deals and short_deals:
                self._log.warning(
                    f"Entrade holds long and short deals in {symbol}; reporting the net position",
                )
            long_quantity = sum((_decimal(d["openQuantity"]) for d in long_deals), Decimal(0))
            short_quantity = sum((_decimal(d["openQuantity"]) for d in short_deals), Decimal(0))
            net_quantity = long_quantity - short_quantity
            if net_quantity == 0:
                continue
            position_side = PositionSide.LONG if net_quantity > 0 else PositionSide.SHORT
            # avg_px_open is taken from the deals on the net side only.
            side_deals = long_deals if net_quantity > 0 else short_deals
            side_quantity = long_quantity if net_quantity > 0 else short_quantity
            weighted_cost = sum(
                (
                    _decimal(deal.get("positionCostPrice") or deal.get("averageCostPrice"))
                    * _decimal(deal["openQuantity"])
                    for deal in side_deals
                ),
                Decimal(0),
            )
            latest_timestamp = max(
                _timestamp_ns(deal.get("modifiedDate"), self.clock.timestamp_ns())
                for deal in open_deals
            )
            reports.append(
                PositionStatusReport(
                    account_id=self.account_id,
                    instrument_id=instrument_id,
                    position_side=position_side,
                    quantity=Quantity.from_decimal_dp(
                        abs(net_quantity), instrument.size_precision
                    ),
                    avg_px_open=weighted_cost / side_quantity,
                    report_id=UUID4(),
                    ts_last=latest_timestamp,
                    ts_init=self.clock.timestamp_ns(),
                ),
            )
        return reports

    def _check_expiry_calendar(self) -> None:
        """Log a WARNING for each loaded contract whose expiry differs from vn30f_expiry_date."""
        assert self._provider is not None
        for contract in self._provider.list_all():
            if not isinstance(contract, FuturesContract):
                continue
            broker_date = (
                datetime.fromtimestamp(contract.expiration_ns / 1e9, tz=VN_TZINFO).date()
            )
            rule_date = vn30f_expiry_date(broker_date.year, broker_date.month)
            if broker_date != rule_date:
                self._log.warning(
                    f"{contract.id} expires on {broker_date} at the broker but "
                    f"vn30f_expiry_date gives {rule_date}; the symbol resolver uses the broker date",
                )

    def _require_account(self) -> None:
        if (
            self._investor_id is None
            or self._investor_account_id is None
            or self._margin_portfolio_id is None
        ):
            raise RuntimeError("Entrade execution client is not connected")


def entrade_account_balance(
    payload: dict[str, Any], currency: Currency
) -> AccountBalance:
    total = _decimal(payload["nav"])
    free = _decimal(payload["availableCash"])
    locked = total - free
    if locked < 0:
        raise ValueError("Entrade availableCash cannot exceed NAV")
    return AccountBalance(
        total=Money.from_decimal(total, currency),
        locked=Money.from_decimal(locked, currency),
        free=Money.from_decimal(free, currency),
    )


def _parse_qmax(payload: dict[str, Any]) -> int:
    value = payload.get("qmax")
    if value is None or isinstance(value, bool):
        raise ValueError("Entrade buying-power response contains invalid qmax")
    try:
        qmax = int(value)
    except (TypeError, ValueError) as e:
        raise ValueError(
            "Entrade buying-power response does not contain a valid qmax"
        ) from e
    if qmax < 0:
        raise ValueError("Entrade buying-power response contains negative qmax")
    return qmax


def _decimal(value: Any) -> Decimal:
    """Parse broker numeric values without introducing binary floating-point arithmetic."""
    if value is None or value == "":
        return Decimal(0)
    return Decimal(str(value))
