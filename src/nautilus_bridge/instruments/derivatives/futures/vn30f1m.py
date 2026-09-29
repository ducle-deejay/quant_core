"""VN30F1M Nautilus instruments and provider."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
from datetime import date
from datetime import timedelta
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


def vn30f_expiry_date(
    year: int,
    month: int,
    is_trading_day: Callable[[date], bool] | None = None,
) -> date:
    """Return the last trading day of the VN30 futures contract expiring in ``year``-``month``.

    HNX rule: the third Thursday of the month, moved back to the previous trading day
    when that Thursday is not a trading day. ``is_trading_day`` defaults to weekdays
    only, so exchange holidays must be supplied by the caller to be honoured.
    """
    is_trading_day = is_trading_day or (lambda day: day.weekday() < 5)
    first = date(year, month, 1)
    first_thursday = first + timedelta(days=(3 - first.weekday()) % 7)
    expiry = first_thursday + timedelta(weeks=2)
    while not is_trading_day(expiry):
        expiry -= timedelta(days=1)
    return expiry


class VN30F1MResolver:
    """Map VN30F1M.HNX to the front-month contract and back.

    The front-month contract is the loaded contract with the earliest ``expiration_ns``
    not before the given time; contracts loaded from Entrade carry 14:45 local time of
    the expiry day. Any other instrument maps to itself.
    """

    def __init__(self, contracts: Callable[[], Iterable[FuturesContract]]) -> None:
        self._contracts = contracts

    def front_contract(self, ts_ns: int) -> FuturesContract | None:
        live = [
            contract
            for contract in self._contracts()
            if isinstance(contract, FuturesContract)
            and contract.id.venue == VENUE
            and contract.expiration_ns >= ts_ns
        ]
        return min(live, key=lambda contract: contract.expiration_ns, default=None)

    def to_venue(self, instrument_id: InstrumentId, ts_ns: int) -> InstrumentId:
        """Instrument an order is sent to at the venue."""
        if instrument_id != CONTINUOUS_ID:
            return instrument_id
        contract = self.front_contract(ts_ns)
        if contract is None:
            raise ValueError(f"No unexpired monthly contract is loaded for {CONTINUOUS_ID}")
        return contract.id

    def to_nautilus(self, instrument_id: InstrumentId, ts_ns: int) -> InstrumentId:
        """Instrument a venue order, fill or position is reported under."""
        contract = self.front_contract(ts_ns)
        if contract is not None and instrument_id == contract.id:
            return CONTINUOUS_ID
        return instrument_id


def _register_currency() -> None:
    Currency.register(VND, overwrite=True)
