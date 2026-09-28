from __future__ import annotations

from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.datetime import secs_to_nanos
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import CustomData
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import MarginAccount
from nautilus_trader.model import OrderSide
from nautilus_trader.model import PositionClosed
from nautilus_trader.model import Price
from nautilus_trader.model import TimeInForce
from nautilus_trader.trading import Strategy

from nautilus_bridge.data.custom_data import ExposureData


class DirectionalStrategyConfig(StrategyConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_type: BarType,
        trade_size: Decimal | None = None,
        limit_offset_ticks: int = 1,
        order_ttl_minutes: int = 3,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type
        self.trade_size = trade_size
        self.limit_offset_ticks = limit_offset_ticks
        self.order_ttl_minutes = order_ttl_minutes


class DirectionalStrategy(Strategy):

    def __init__(self, config: DirectionalStrategyConfig) -> None:
        super().__init__(config)
        self.instrument = None
        self.last_target_exposure: float | None = None
        self.target_contracts = 0

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.subscribe_data(ExposureData.TYPE)

    def on_data(self, exposure_data: CustomData) -> None:
        target_exposure = exposure_data.data.target_exposure
        # Only a new alpha decision changes the target; repeated values are ignored
        if target_exposure == self.last_target_exposure:
            return
        self.last_target_exposure = target_exposure

        if self.instrument is None:
            return

        bar = self.cache.bar(self.config.bar_type.standard())
        if bar is None:
            return

        # Portfolio.account() clones the account with its full event history, so fetch it once
        account = self.portfolio.account(self.config.instrument_id.venue)
        if self.config.trade_size is not None:
            # Fixed size for debugging: exposure +-1 maps to +-trade_size contracts
            self.target_contracts = int(self.config.trade_size * Decimal(str(target_exposure)))
        else:
            self.target_contracts = self._exposure_to_contracts(target_exposure, bar.close, account)
        target_contracts = self.target_contracts
        current_contracts = int(self.portfolio.net_position(self.config.instrument_id))
        if target_contracts == current_contracts:
            return

        # (a) Same-direction increase, e.g. 2 -> 3
        is_increasing_position = (
            target_contracts > current_contracts >= 0
            or target_contracts < current_contracts <= 0
        )
        if is_increasing_position:
            qty_to_target = abs(target_contracts) - abs(current_contracts)
            self._submit_opening_order(qty_to_target, bar, account)
            return

        # (b) reduce, (c) go flat, (d) reverse: close with a reduce-only order first
        is_reversing = target_contracts * current_contracts < 0
        if is_reversing or target_contracts == 0:
            reduce_qty = abs(current_contracts)
        else:
            reduce_qty = abs(current_contracts) - abs(target_contracts)
        close_side = OrderSide.SELL if current_contracts > 0 else OrderSide.BUY
        close_price = self._marketable_price(close_side, bar)
        self._submit_order(close_side, reduce_qty, close_price, reduce_only=True)

    def on_position_closed(self, event: PositionClosed) -> None:
        # (d) second leg of a reversal: open the new side once flat
        if self.target_contracts == 0:
            return
        bar = self.cache.bar(self.config.bar_type.standard())
        if bar is None:
            return
        account = self.portfolio.account(self.config.instrument_id.venue)
        self._submit_opening_order(abs(self.target_contracts), bar, account)

    def _submit_opening_order(self, qty_to_target: int, bar: Bar, account: MarginAccount) -> None:
        side = OrderSide.BUY if self.target_contracts > 0 else OrderSide.SELL
        # Check margin at the order's own limit price, as the risk engine does
        price = self._marketable_price(side, bar)
        order_qty = min(qty_to_target, self._max_openable_contracts(price, account))
        if order_qty <= 0:
            return
        self._submit_order(side, order_qty, price, reduce_only=False)

    def _submit_order(
        self, side: OrderSide, quantity: int, price: Price, reduce_only: bool
    ) -> None:
        order = self.order_factory.limit(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=self.instrument.make_qty(quantity),
            price=price,
            time_in_force=TimeInForce.GTD,
            expire_time=self.clock.timestamp_ns()
            + secs_to_nanos(self.config.order_ttl_minutes * 60),
            reduce_only=reduce_only,
        )
        self.submit_order(order)

    def _exposure_to_contracts(self, exposure: float, price: Price, account: MarginAccount) -> int:
        # Size on total (not free), so the result does not shrink with the held position
        total = account.balance_total(self.instrument.settlement_currency).as_decimal()
        margin_per_contract = self._initial_margin_per_contract(price, account)
        # int() truncates toward zero, so |contracts| never exceeds what total can margin
        return int(Decimal(str(exposure)) * total / margin_per_contract)

    def _max_openable_contracts(self, price: Price, account: MarginAccount) -> int:
        # Nautilus defines free = total - locked, the amount available for new orders
        free = account.balance_free(self.instrument.settlement_currency).as_decimal()
        margin_per_contract = self._initial_margin_per_contract(price, account)
        # A negative free balance opens nothing
        return max(int(free // margin_per_contract), 0)

    def _initial_margin_per_contract(self, price: Price, account: MarginAccount) -> Decimal:
        # Delegates to the venue's configured margin model
        return account.calculate_initial_margin(
            self.instrument,
            self.instrument.make_qty(1),
            price,
        ).as_decimal()

    def _marketable_price(self, side: OrderSide, bar: Bar) -> Price:
        tick = self.instrument.price_increment.as_double()
        offset = self.config.limit_offset_ticks * tick
        reference = bar.close.as_double()
        price = reference + offset if side == OrderSide.BUY else reference - offset
        return self.instrument.make_price(price)

    def on_stop(self) -> None:
        # Clear the target first so on_position_closed does not reopen
        self.target_contracts = 0
        self.last_target_exposure = None
        self.close_all_positions(self.config.instrument_id)
