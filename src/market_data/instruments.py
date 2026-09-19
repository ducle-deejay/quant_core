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
    PerpetualContract,
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

    def to_dict(self) -> dict:
        """Return the JSON-native field mapping used by str/from_str."""
        return {
            "symbol": self.symbol,
            "venue": self.venue,
            "underlying": self.underlying,
            "currency_code": self.currency_code,
            "currency_precision": self.currency_precision,
            "currency_iso4217": self.currency_iso4217,
            "currency_name": self.currency_name,
            "price_precision": self.price_precision,
            "price_increment": self.price_increment,
            "multiplier": self.multiplier,
            "lot_size": self.lot_size,
            "exchange": self.exchange,
            "asset_class": self.asset_class.name,
            "currency_type": self.currency_type.name,
            "size_precision": self.size_precision,
            "vsd_initial_margin_ratio": self.vsd_initial_margin_ratio,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FuturesInstrumentSpec:
        """Restore a spec from the to_dict mapping."""
        return cls(
            symbol=data["symbol"],
            venue=data["venue"],
            underlying=data["underlying"],
            currency_code=data["currency_code"],
            currency_precision=data["currency_precision"],
            currency_iso4217=data["currency_iso4217"],
            currency_name=data["currency_name"],
            price_precision=data["price_precision"],
            price_increment=data["price_increment"],
            multiplier=data["multiplier"],
            lot_size=data["lot_size"],
            exchange=data.get("exchange"),
            asset_class=AssetClass.from_str(data["asset_class"]),
            currency_type=CurrencyType.from_str(data["currency_type"]),
            size_precision=data.get("size_precision", 0),
            vsd_initial_margin_ratio=data.get("vsd_initial_margin_ratio"),
        )

    def __str__(self) -> str:
        # Nautilus config serialization encodes values whose type exposes
        # from_str as str(value); the canonical string is a stable JSON map.
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_str(cls, value: str) -> FuturesInstrumentSpec:
        return cls.from_dict(json.loads(value))


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


def build_continuous_futures_proxy(
    spec: FuturesInstrumentSpec,
    *,
    ts_event_ns: int | None = None,
    record_ts_init_ns: int | None = None,
) -> PerpetualContract:
    """Compose the non-expiring execution proxy for the continuous price series."""
    register_futures_instrument_currency(spec)
    quote_currency = spec.quote_currency()
    ts_event = 0 if ts_event_ns is None else ts_event_ns
    ts_init = 0 if record_ts_init_ns is None else record_ts_init_ns

    return PerpetualContract(
        instrument_id=spec.instrument_id(),
        raw_symbol=spec.instrument_id().symbol,
        underlying=spec.underlying,
        asset_class=spec.asset_class,
        base_currency=None,
        quote_currency=quote_currency,
        settlement_currency=quote_currency,
        is_inverse=False,
        price_precision=spec.price_precision,
        size_precision=spec.size_precision,
        price_increment=spec.price_increment_object(),
        size_increment=Quantity(1, spec.size_precision),
        multiplier=spec.multiplier_object(),
        lot_size=spec.lot_size_object(),
        ts_event=ts_event,
        ts_init=ts_init,
    )


def _precision_from_increment(value: float) -> int:
    text = format(value, "f").rstrip("0").rstrip(".")
    return len(text.split(".", 1)[1]) if "." in text else 0


def _infer_underlying(symbol: str) -> str:
    return symbol.removesuffix("F1M")
