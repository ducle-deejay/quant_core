"""VN30F1M Nautilus instruments and provider."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
from nautilus_trader.live.providers import InstrumentProvider
from nautilus_trader.model import AssetClass
from nautilus_trader.model import Currency
from nautilus_trader.model import CurrencyType
from nautilus_trader.model import FuturesContract
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import PerpetualContract
from nautilus_trader.model import Price
from nautilus_trader.model import Quantity
from nautilus_trader.model import Symbol
from nautilus_trader.model import Venue


VENUE = Venue("HNX")
EXCHANGE = "HSTC"
UNDERLYING = "VN30"
CONTINUOUS_SYMBOL = Symbol("VN30F1M")
CONTINUOUS_ID = InstrumentId(CONTINUOUS_SYMBOL, VENUE)
VND = Currency("VND", 0, 704, "Vietnamese dong", CurrencyType.FIAT)
PRICE_INCREMENT = Price.from_str("0.1")
PRICE_PRECISION = 1
SIZE_INCREMENT = Quantity.from_int(1)
MULTIPLIER = Quantity.from_int(100_000)
LOT_SIZE = Quantity.from_int(1)
# EnTrade rates are 0.05 initial margin, 0.03 maintenance margin, and a 0.02
# force-sell threshold. Use 4x margin rates as a conservative risk buffer.
MARGIN_INIT = Decimal("0.2")
MARGIN_MAINT = Decimal("0.12")


def build_monthly_futures_contract(
    symbol: str,
    activation: str | None,
    expiration: str,
    *,
    ts_event: int | None = None,
    ts_init: int | None = None,
    info: dict[str, object] | None = None,
) -> FuturesContract:
    """Build one dated VN30 futures contract."""
    _register_currency()
    instrument_id = InstrumentId(Symbol(symbol), VENUE)
    activation_ns = 0 if activation is None else pd.Timestamp(activation, tz="UTC").value
    expiration_ns = pd.Timestamp(expiration, tz="UTC").value
    return FuturesContract(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        asset_class=AssetClass.INDEX,
        exchange=EXCHANGE,
        currency=VND,
        price_precision=PRICE_PRECISION,
        price_increment=PRICE_INCREMENT,
        multiplier=MULTIPLIER,
        lot_size=LOT_SIZE,
        underlying=UNDERLYING,
        activation_ns=activation_ns,
        expiration_ns=expiration_ns,
        margin_init=MARGIN_INIT,
        margin_maint=MARGIN_MAINT,
        ts_event=activation_ns if ts_event is None else ts_event,
        ts_init=activation_ns if ts_init is None else ts_init,
        info=info,
    )


def build_continuous_futures_contract(
    symbol: str = CONTINUOUS_SYMBOL.value,
    *,
    ts_event: int | None = None,
    ts_init: int | None = None,
) -> PerpetualContract:
    """Build the non-expiring VN30F1M execution proxy."""
    _register_currency()
    instrument_id = InstrumentId(Symbol(symbol), VENUE)
    return PerpetualContract(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        underlying=UNDERLYING,
        asset_class=AssetClass.INDEX,
        base_currency=None,
        quote_currency=VND,
        settlement_currency=VND,
        is_inverse=False,
        price_precision=PRICE_PRECISION,
        size_precision=0,
        price_increment=PRICE_INCREMENT,
        size_increment=SIZE_INCREMENT,
        multiplier=MULTIPLIER,
        lot_size=LOT_SIZE,
        margin_init=MARGIN_INIT,
        margin_maint=MARGIN_MAINT,
        ts_event=0 if ts_event is None else ts_event,
        ts_init=0 if ts_init is None else ts_init,
    )


class VN30F1MInstrumentProvider(InstrumentProvider):
    """Provide VN30F1M through the Nautilus instrument-provider contract."""

    async def load_all_async(self, filters: dict | None = None) -> None:
        self.add(build_continuous_futures_contract())

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        if CONTINUOUS_ID in set(instrument_ids):
            self.add(build_continuous_futures_contract())


def _register_currency() -> None:
    Currency.register(VND, overwrite=True)
