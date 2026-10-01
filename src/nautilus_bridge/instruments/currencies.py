from __future__ import annotations

from nautilus_trader.model import Currency
from nautilus_trader.model import CurrencyType

VND = Currency("VND", 0, 704, "Vietnamese dong", CurrencyType.FIAT)


def register_currencies() -> None:
    # Money.from_str accepts only registered currencies, and VND is not built in
    Currency.register(VND, overwrite=True)
