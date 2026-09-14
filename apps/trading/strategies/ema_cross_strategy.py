"""Strategy trading the signal published by ``EMACrossActor``.

Adapted from the EMACross reference strategy
(docs/tutorials/ema_cross.py in the nautilus_trader repository). Order
execution only: the trading decision arrives as a signal published by
trading.actors.ema_cross_actor.EMACrossActor.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import OrderSide
from nautilus_trader.trading import Strategy

from actors.ema_cross_actor import SIGNAL_NAME


class EMACrossStrategyConfig(StrategyConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        trade_size: Decimal,
        signal_name: str = SIGNAL_NAME,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.trade_size = trade_size
        self.signal_name = signal_name


class EMACrossStrategy(Strategy):
    """Target long on a positive signal and short on a negative signal."""

    def __init__(self, config: EMACrossStrategyConfig) -> None:
        super().__init__(config)
        self.instrument = None

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.subscribe_signal(self.config.signal_name)

    def on_signal(self, signal) -> None:
        if self.instrument is None:
            return
        if signal.value == "LONG":
            if self.portfolio.is_net_flat(self.config.instrument_id):
                self.buy()
            elif self.portfolio.is_net_short(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)
                self.buy()
        elif signal.value == "SHORT":
            if self.portfolio.is_net_flat(self.config.instrument_id):
                self.sell()
            elif self.portfolio.is_net_long(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)
                self.sell()

    def buy(self) -> None:
        order = self.order_factory.market(
            self.config.instrument_id,
            OrderSide.BUY,
            self.instrument.make_qty(self.config.trade_size),
        )
        self.submit_order(order)

    def sell(self) -> None:
        order = self.order_factory.market(
            self.config.instrument_id,
            OrderSide.SELL,
            self.instrument.make_qty(self.config.trade_size),
        )
        self.submit_order(order)

    def on_stop(self) -> None:
        self.close_all_positions(self.config.instrument_id)
