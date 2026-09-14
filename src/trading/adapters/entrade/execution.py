from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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
    TimeInForce,
    TradeId,
    TraderId,
    Venue,
    VenueOrderId,
)

from trading.adapters.entrade.client import EntradeClient, investor_id_from_token
from trading.adapters.entrade.config import (
    DNSE_EXECUTION_CLIENT_NAME,
    EntradeExecClientConfig,
)
from trading.adapters.entrade.contracts import EntradeMonthlyContract
from trading.adapters.entrade.instruments import EntradeInstrumentProvider
from trading.adapters.entrade.transport import EntradeClientConfig

ORDER_POLL_INTERVAL_SECONDS = 1.0


@dataclass
class EntradeOrderContext:
    order: Any
    venue_order_id: VenueOrderId
    reported_fills: set[str]
    last_status: str | None = None


ENTRADE_TERMINAL_STATUSES = {"Canceled", "Expired", "Filled", "Rejected"}


def entrade_order_parameters(order: Any) -> tuple[str, str, int, float]:
    side = "NB" if order.side == OrderSide.BUY else "NS"
    quantity_decimal = order.quantity.as_decimal()
    if quantity_decimal != quantity_decimal.to_integral_value():
        raise ValueError("Entrade derivative order quantity must be a whole number")
    quantity = int(quantity_decimal)

    if order.order_type == OrderType.LIMIT and order.time_in_force in {
        TimeInForce.DAY,
        TimeInForce.GTC,
    }:
        return side, "LO", quantity, order.price.as_double()
    if order.order_type == OrderType.MARKET_TO_LIMIT:
        return side, "MTL", quantity, 0.0
    if order.order_type == OrderType.MARKET and order.time_in_force == TimeInForce.IOC:
        return side, "MAK", quantity, 0.0
    if order.order_type == OrderType.MARKET and order.time_in_force == TimeInForce.FOK:
        return side, "MOK", quantity, 0.0
    raise ValueError(
        f"Unsupported Entrade order combination: {order.order_type.name} "
        f"with {order.time_in_force.name}",
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
    """Nautilus execution-client extension backed by Entrade."""

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
    ) -> None:
        if not isinstance(config, EntradeExecClientConfig):
            raise TypeError("Expected EntradeExecClientConfig")
        super().__init__(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            trader_id=trader_id,
            venue=Venue(config.instrument_spec.venue),
            account_id=AccountId(config.account_id),
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=config.instrument_spec.quote_currency(),
            instrument_provider=instrument_provider,
        )
        self._client = client
        self._provider = instrument_provider
        self._config = config
        self._investor_id: int | str | None = config.investor_id
        self._investor_account_id: int | str | None = None
        self._margin_portfolio_id: int | None = None
        self._active_contract: EntradeMonthlyContract | None = None
        self._orders: dict[ClientOrderId, EntradeOrderContext] = {}
        self._client_order_ids: dict[VenueOrderId, ClientOrderId] = {}
        self._provider = instrument_provider

    @property
    def investor_id(self) -> int | str | None:
        return self._investor_id

    @property
    def active_contract(self) -> EntradeMonthlyContract | None:
        return self._active_contract

    async def _connect(self) -> None:
        if not self._config.username or not self._config.password:
            raise ValueError("Entrade username and password are required")
        if self._client is None:
            self._client = EntradeClient(
                EntradeClientConfig(
                    environment=self._config.environment,
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

        await self._provider.load_all_async()
        self._active_contract = self._provider.resolve_active_contract()
        for instrument in self._provider.list_all():
            self._handle_instrument(instrument)
        self._generate_balance(balance)

    async def _disconnect(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)

    async def _query_account(self, command: QueryAccount) -> None:
        if self._investor_id is None or self._client is None:
            raise RuntimeError("Entrade execution client is not authenticated")
        balance = await asyncio.to_thread(
            self._client.get_account_balance, self._investor_id
        )
        self._generate_balance(balance)

    def _generate_balance(self, payload: dict[str, Any]) -> None:
        balance = entrade_account_balance(
            payload, self._config.instrument_spec.quote_currency()
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
        payload = await asyncio.to_thread(
            self._client.list_orders,
            investor_account_id=self._investor_account_id,
            end=255,
        )
        reports = [
            self._order_status_report(order) for order in payload.get("data", [])
        ]
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
            payload = await asyncio.to_thread(
                self._client.list_orders,
                investor_account_id=self._investor_account_id,
                end=255,
            )
            orders = payload.get("data", [])
        reports = [report for order in orders for report in self._fill_reports(order)]
        if command.instrument_id is not None:
            reports = [
                report
                for report in reports
                if report.instrument_id == command.instrument_id
            ]
        return reports

    async def _generate_position_status_reports(
        self,
        command: GeneratePositionStatusReports,
    ) -> list[PositionStatusReport]:
        self._require_account()
        assert self._client is not None
        payload = await asyncio.to_thread(
            self._client.list_deals,
            investor_account_id=self._investor_account_id,
            end=255,
        )
        reports = self._position_status_reports(payload.get("data", []))
        if command.instrument_id is None:
            return reports
        if command.instrument_id == self._config.instrument_spec.instrument_id():
            return reports
        return [
            report
            for report in reports
            if report.instrument_id == command.instrument_id
        ]

    async def _generate_mass_status(
        self, lookback_mins: int | None = None
    ) -> ExecutionMassStatus | None:
        self._require_account()
        assert self._client is not None
        balance, orders_payload, deals_payload = await asyncio.gather(
            asyncio.to_thread(self._client.get_account_balance, self._investor_id),
            asyncio.to_thread(
                self._client.list_orders,
                investor_account_id=self._investor_account_id,
                end=255,
            ),
            asyncio.to_thread(
                self._client.list_deals,
                investor_account_id=self._investor_account_id,
                end=255,
            ),
        )
        self._generate_balance(balance)

        order_payloads = orders_payload.get("data", [])
        if lookback_mins is not None:
            cutoff_ns = self.clock.timestamp_ns() - lookback_mins * 60 * 1_000_000_000
            order_payloads = [
                payload
                for payload in order_payloads
                if _timestamp_ns(payload.get("modifiedDate"), 0) >= cutoff_ns
            ]
        order_reports = [
            self._order_status_report(payload) for payload in order_payloads
        ]
        fill_reports = [
            report
            for payload in order_payloads
            for report in self._fill_reports(payload)
        ]
        position_reports = self._position_status_reports(deals_payload.get("data", []))

        mass_status = ExecutionMassStatus(
            client_id=self.client_id,
            account_id=self.account_id,
            venue=self.venue,
            report_id=UUID4(),
            ts_init=self.clock.timestamp_ns(),
        )
        mass_status.add_order_reports(order_reports)
        mass_status.add_fill_reports(fill_reports)
        mass_status.add_position_reports(position_reports)
        return mass_status

    async def _submit_order(self, command: SubmitOrder) -> None:
        await self._submit_order_object(command.order)

    async def _submit_order_object(self, order: Any) -> None:
        try:
            self._require_account()
            if self._provider is None or self._client is None:
                raise RuntimeError("Entrade execution client is not connected")
            side, order_type, quantity, price = entrade_order_parameters(order)
            contract = self._provider.contract_for_instrument(order.instrument_id)
            if contract is None:
                raise ValueError(
                    "Entrade orders must name a concrete monthly contract",
                )
            reference_price = price or contract.market_price or contract.basic_price
            if reference_price is None:
                raise ValueError(
                    f"Entrade buying-power check has no reference price for {contract.symbol}",
                )
            buying_power = await asyncio.to_thread(
                self._client.get_buying_power,
                investor_id=self._investor_id,
                margin_portfolio_id=self._margin_portfolio_id,
                symbol=contract.symbol,
                side=side,
                price=reference_price,
            )
            qmax = _parse_qmax(buying_power)
            quantity = min(quantity, qmax)
            if quantity < 1:
                raise ValueError(
                    f"Entrade qmax is zero for {contract.symbol} {side}",
                )
        except (RuntimeError, ValueError) as e:
            self.generate_order_rejected(
                order, str(e), self.clock.timestamp_ns(), False
            )
            return

        self.generate_order_submitted(order)
        try:
            assert self._client is not None
            payload = await asyncio.to_thread(
                self._client.place_order,
                investor_id=self._investor_id,
                margin_portfolio_id=self._margin_portfolio_id,
                symbol=contract.symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
            )
        except Exception as e:  # noqa: BLE001 - broker errors become order rejections.
            self.generate_order_rejected(
                order,
                f"Entrade order submission failed: {e}",
                self.clock.timestamp_ns(),
                False,
            )
            return

        broker_order_id = payload.get("id")
        if broker_order_id is None:
            self.generate_order_rejected(
                order,
                "Entrade order response did not contain an ID",
                self.clock.timestamp_ns(),
                False,
            )
            return

        venue_order_id = VenueOrderId(str(broker_order_id))
        context = EntradeOrderContext(order, venue_order_id, set())
        self._orders[order.client_order_id] = context
        self._client_order_ids[venue_order_id] = order.client_order_id
        self.generate_order_accepted(
            order,
            venue_order_id,
            _timestamp_ns(payload.get("createdDate"), self.clock.timestamp_ns()),
        )
        if quantity < int(order.quantity.as_decimal()):
            instrument = self._provider.find(order.instrument_id)
            if instrument is not None:
                self.generate_order_updated(
                    order,
                    venue_order_id,
                    Quantity.from_decimal_dp(
                        Decimal(quantity), instrument.size_precision
                    ),
                    getattr(order, "price", None)
                    if getattr(order, "has_price", False)
                    else None,
                    getattr(order, "trigger_price", None)
                    if getattr(order, "has_trigger_price", False)
                    else None,
                    None,
                    self.clock.timestamp_ns(),
                )
        self._synchronize_order(payload, context)
        if payload.get("orderStatus") not in ENTRADE_TERMINAL_STATUSES:
            self.create_task(
                self._poll_order(context),
                name=f"poll_entrade_order: {venue_order_id.value}",
            )

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
        if order is not None:
            self.generate_order_modify_rejected(
                order,
                command.venue_order_id,
                "Entrade order modification is not supported by the current MVP adapter",
                self.clock.timestamp_ns(),
            )

    async def _cancel_order(self, command: CancelOrder) -> None:
        context = self._orders.get(command.client_order_id)
        venue_order_id = command.venue_order_id or (
            context.venue_order_id if context else None
        )
        order = (
            context.order
            if context
            else self._order_for_client_id(command.client_order_id)
        )
        if venue_order_id is None or context is None or order is None:
            if order is not None:
                self.generate_order_cancel_rejected(
                    order,
                    venue_order_id,
                    "Entrade broker order ID is not known",
                    self.clock.timestamp_ns(),
                )
            return
        try:
            assert self._client is not None
            payload = await asyncio.to_thread(
                self._client.cancel_order, venue_order_id.value
            )
        except Exception as e:  # noqa: BLE001 - broker errors become cancel rejections.
            self.generate_order_cancel_rejected(
                order,
                venue_order_id,
                f"Entrade order cancellation failed: {e}",
                self.clock.timestamp_ns(),
            )
            return
        self._synchronize_order(payload, context)

    async def _cancel_all_orders(self, command: CancelAllOrders) -> None:
        for order in self.cache.orders_open(instrument_id=command.instrument_id):
            context = self._orders.get(order.client_order_id)
            if context is None:
                continue
            assert self._client is not None
            payload = await asyncio.to_thread(
                self._client.cancel_order, context.venue_order_id.value
            )
            self._synchronize_order(payload, context)

    async def _batch_cancel_orders(self, command: BatchCancelOrders) -> None:
        for cancel in command.cancels:
            await self._cancel_order(cancel)

    async def _poll_order(self, context: EntradeOrderContext) -> None:
        if self._client is None:
            return
        while True:
            await asyncio.sleep(ORDER_POLL_INTERVAL_SECONDS)
            payload = await asyncio.to_thread(
                self._client.get_order, context.venue_order_id.value
            )
            self._synchronize_order(payload, context)
            if payload.get("orderStatus") in ENTRADE_TERMINAL_STATUSES:
                return

    def _synchronize_order(
        self, payload: dict[str, Any], context: EntradeOrderContext
    ) -> None:
        order = context.order
        for fill in self._fill_reports(payload, client_order_id=order.client_order_id):
            fill_key = fill.trade_id.value
            if fill_key in context.reported_fills:
                continue
            context.reported_fills.add(fill_key)
            self.generate_order_filled(
                order,
                context.venue_order_id,
                None,
                fill.trade_id,
                fill.last_qty,
                fill.last_px,
                self._config.instrument_spec.quote_currency(),
                fill.commission,
                fill.liquidity_side,
                fill.ts_event,
            )

        status = payload.get("orderStatus")
        if not status or status == context.last_status:
            return
        context.last_status = status
        ts_event = _timestamp_ns(payload.get("modifiedDate"), self.clock.timestamp_ns())
        if status == "Canceled":
            self.generate_order_canceled(order, context.venue_order_id, ts_event)
        elif status == "Expired":
            self.generate_order_expired(order, context.venue_order_id, ts_event)
        elif status == "Rejected":
            self.generate_order_rejected(
                order,
                str(payload.get("rejectReason") or "Entrade rejected the order"),
                ts_event,
                False,
            )

    def _order_status_report(self, payload: dict[str, Any]) -> OrderStatusReport:
        venue_order_id = VenueOrderId(str(payload["id"]))
        client_order_id = self._client_order_ids.get(venue_order_id)
        context = self._orders.get(client_order_id) if client_order_id else None
        instrument_id = (
            context.order.instrument_id
            if context is not None
            else InstrumentId.from_str(f"{payload['symbol']}.{self.venue.value}")
        )
        if self._provider is None:
            raise RuntimeError("Entrade instrument provider is not connected")
        instrument = self._provider.find(instrument_id)
        if instrument is None:
            instrument = self._provider.find(
                self._config.instrument_spec.instrument_id()
            )
        if instrument is None:
            raise ValueError(f"No instrument loaded for Entrade order {payload['id']}")
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
        instrument_id = (
            context.order.instrument_id
            if context is not None
            else InstrumentId.from_str(f"{payload['symbol']}.{self.venue.value}")
        )
        if self._provider is None:
            raise RuntimeError("Entrade instrument provider is not connected")
        instrument = self._provider.find(instrument_id)
        if instrument is None:
            instrument = self._provider.find(
                self._config.instrument_spec.instrument_id()
            )
        if instrument is None:
            raise ValueError(f"No instrument loaded for Entrade fill {payload['id']}")

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
                        self._config.instrument_spec.quote_currency(),
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
            grouped.setdefault(str(deal["symbol"]), []).append(deal)

        reports: list[PositionStatusReport] = []
        for symbol, open_deals in grouped.items():
            broker_sides = {deal["side"] for deal in open_deals}
            if not broker_sides <= {"NB", "NS"}:
                raise ValueError(
                    f"Unsupported Entrade position side for {symbol}: {broker_sides}"
                )
            if len(broker_sides) != 1:
                raise ValueError(
                    f"Entrade returned opposing active deals for netting instrument {symbol}",
                )

            instrument_id = InstrumentId.from_str(f"{symbol}.{self.venue.value}")
            if self._provider is None:
                raise RuntimeError("Entrade instrument provider is not connected")
            instrument = self._provider.find(instrument_id)
            if instrument is None:
                raise ValueError(f"No instrument loaded for Entrade position {symbol}")

            broker_side = next(iter(broker_sides))
            position_side = (
                PositionSide.LONG if broker_side == "NB" else PositionSide.SHORT
            )
            quantity = sum(
                (_decimal(deal["openQuantity"]) for deal in open_deals), Decimal(0)
            )
            weighted_cost = sum(
                _decimal(deal.get("positionCostPrice") or deal.get("averageCostPrice"))
                * _decimal(deal["openQuantity"])
                for deal in open_deals
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
                        quantity, instrument.size_precision
                    ),
                    avg_px_open=(weighted_cost / quantity if quantity else None),
                    report_id=UUID4(),
                    ts_last=latest_timestamp,
                    ts_init=self.clock.timestamp_ns(),
                ),
            )
        return reports

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
