from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd
from nautilus_trader.model import (
    AssetClass,
    Currency,
    CurrencyType,
    FuturesContract,
    InstrumentId,
    Price,
    Quantity,
    Symbol,
    Venue,
)

try:
    from nautilus_trader.model.currencies import register_currency
except ModuleNotFoundError:
    # Nautilus rc5 moved registration onto the Currency type.
    def register_currency(currency: Currency, overwrite: bool = False) -> None:
        Currency.register(currency, overwrite=overwrite)


@dataclass(frozen=True)
class FuturesInstrumentSpec:
    """Market-data contract for constructing a Nautilus futures instrument."""

    symbol: str
    venue: str
    underlying: str
    currency_code: str
    currency_precision: int
    currency_iso4217: int
    currency_name: str
    price_precision: int
    price_increment: float
    multiplier: int
    lot_size: int
    exchange: str | None = None
    asset_class: AssetClass = AssetClass.INDEX
    currency_type: CurrencyType = CurrencyType.FIAT
    size_precision: int = 0
    vsd_initial_margin_ratio: float | None = None

    def instrument_id(self) -> InstrumentId:
        return InstrumentId(Symbol(self.symbol), Venue(self.venue))

    def quote_currency(self) -> Currency:
        return Currency(
            self.currency_code,
            self.currency_precision,
            self.currency_iso4217,
            self.currency_name,
            self.currency_type,
        )

    def price_increment_object(self) -> Price:
        return Price(self.price_increment, self.price_precision)

    def multiplier_object(self) -> Quantity:
        return Quantity(self.multiplier, self.size_precision)

    def lot_size_object(self) -> Quantity:
        return Quantity(self.lot_size, self.size_precision)

    def with_symbol(self, symbol: str) -> FuturesInstrumentSpec:
        return replace(self, symbol=symbol)


def load_futures_instrument_spec(path: str | Path) -> FuturesInstrumentSpec:
    """Load the futures instrument contract from JSON."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    symbol = payload["symbol"]
    tick_size = float(payload["tick_size"])
    currency_code = payload.get("currency", "VND")
    return FuturesInstrumentSpec(
        symbol=symbol,
        venue=payload["venue"],
        underlying=payload.get("underlying", _infer_underlying(symbol)),
        currency_code=currency_code,
        currency_precision=int(
            payload.get("currency_precision", 0 if currency_code == "VND" else 2)
        ),
        currency_iso4217=int(payload.get("currency_iso4217", 704)),
        currency_name=payload.get("currency_name", "Vietnamese dong"),
        price_precision=int(
            payload.get("price_precision", _precision_from_increment(tick_size))
        ),
        price_increment=tick_size,
        multiplier=int(payload["multiplier"]),
        lot_size=int(payload.get("lot_size", 1)),
        exchange=payload.get("exchange"),
        size_precision=int(payload.get("size_precision", 0)),
        vsd_initial_margin_ratio=payload.get("vsd_initial_margin_ratio"),
    )


def register_futures_instrument_currency(spec: FuturesInstrumentSpec) -> None:
    """Register the configured currency for catalog serialization round trips."""
    register_currency(spec.quote_currency(), overwrite=True)


def build_futures_contract(
    spec: FuturesInstrumentSpec,
    activation: str | None,
    expiration: str,
    *,
    ts_event: int | None = None,
    ts_init: int | None = None,
    info: dict[str, object] | None = None,
) -> FuturesContract:
    """Compose a monthly Nautilus futures contract from explicit metadata."""
    register_futures_instrument_currency(spec)
    activation_ns = (
        0 if activation is None else pd.Timestamp(activation, tz="UTC").value
    )
    expiration_ns = pd.Timestamp(expiration, tz="UTC").value

    return FuturesContract(
        instrument_id=spec.instrument_id(),
        raw_symbol=spec.instrument_id().symbol,
        asset_class=spec.asset_class,
        exchange=spec.exchange,
        currency=spec.quote_currency(),
        price_precision=spec.price_precision,
        price_increment=spec.price_increment_object(),
        multiplier=spec.multiplier_object(),
        lot_size=spec.lot_size_object(),
        underlying=spec.underlying,
        activation_ns=activation_ns,
        expiration_ns=expiration_ns,
        ts_event=activation_ns if ts_event is None else ts_event,
        ts_init=activation_ns if ts_init is None else ts_init,
        info=info,
    )


def build_continuous_futures_contract(
    spec: FuturesInstrumentSpec,
    ts_init: str | None = None,
    expiration: str | None = None,
    *,
    ts_event_ns: int | None = None,
    record_ts_init_ns: int | None = None,
) -> FuturesContract:
    """Compose the continuous signal instrument used by the data pipeline."""
    if (ts_init is None) != (expiration is None):
        raise ValueError(
            "Continuous instrument window requires both ts_init and expiration"
        )

    register_futures_instrument_currency(spec)
    ts_init_ns = 0 if ts_init is None else pd.Timestamp(ts_init, tz="UTC").value
    expiration_ns = (
        0 if expiration is None else pd.Timestamp(expiration, tz="UTC").value
    )

    return FuturesContract(
        instrument_id=spec.instrument_id(),
        raw_symbol=spec.instrument_id().symbol,
        asset_class=spec.asset_class,
        exchange=spec.exchange,
        currency=spec.quote_currency(),
        price_precision=spec.price_precision,
        price_increment=spec.price_increment_object(),
        multiplier=spec.multiplier_object(),
        lot_size=spec.lot_size_object(),
        underlying=spec.underlying,
        activation_ns=ts_init_ns,
        expiration_ns=expiration_ns,
        ts_event=ts_init_ns if ts_event_ns is None else ts_event_ns,
        ts_init=ts_init_ns if record_ts_init_ns is None else record_ts_init_ns,
    )


def _precision_from_increment(value: float) -> int:
    text = format(value, "f").rstrip("0").rstrip(".")
    return len(text.split(".", 1)[1]) if "." in text else 0


def _infer_underlying(symbol: str) -> str:
    return symbol.removesuffix("F1M")
