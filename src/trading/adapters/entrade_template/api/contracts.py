from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from nautilus_trader.model import FuturesContract

from market_data.instruments import FuturesInstrumentSpec, build_futures_contract

VN30_FRONT_MONTH_SYMBOL = "VN30F1M"
VN_TZINFO = ZoneInfo("Asia/Ho_Chi_Minh")
# HNX index futures trade through 14:45 local time on the final trading day.
VN30_MARKET_CLOSE_LOCAL = time(14, 45)
UNKNOWN_ACTIVATION = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class EntradeMonthlyContract:
    """External boundary representation of an Entrade monthly contract."""

    symbol: str
    contract_type: str
    expiration_date: date
    activation: datetime | None
    market_price: float | None
    basic_price: float | None
    floor_price: float | None
    ceiling_price: float | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> EntradeMonthlyContract:
        return cls(
            symbol=str(payload["symbol"]),
            contract_type=str(payload.get("type", "")),
            expiration_date=_parse_date(payload["expirationDate"]),
            # Entrade currently lists only contracts which are available to trade,
            # but its derivative payload does not publish the first trading date.
            activation=None,
            market_price=_optional_float(payload.get("marketPrice")),
            basic_price=_optional_float(payload.get("basicPrice")),
            floor_price=_optional_float(payload.get("floorPrice")),
            ceiling_price=_optional_float(payload.get("ceilingPrice")),
        )

    @property
    def trading_cutoff(self) -> datetime:
        return datetime.combine(
            self.expiration_date,
            VN30_MARKET_CLOSE_LOCAL,
            tzinfo=VN_TZINFO,
        ).astimezone(UTC)

    @property
    def expiration(self) -> datetime:
        return datetime.combine(
            self.expiration_date,
            VN30_MARKET_CLOSE_LOCAL,
            tzinfo=VN_TZINFO,
        ).astimezone(UTC)

    def to_nautilus_instrument(
        self,
        spec: FuturesInstrumentSpec,
        ts_event: int | None = None,
        ts_init: int | None = None,
    ) -> FuturesContract:
        activation = self.activation or UNKNOWN_ACTIVATION
        return build_futures_contract(
            spec=spec.with_symbol(self.symbol),
            activation=activation.isoformat(),
            expiration=self.expiration.isoformat(),
            ts_event=ts_event,
            ts_init=ts_init,
        )


def resolve_active_contract(
    payload: dict[str, Any],
    *,
    logical_symbol: str,
    at: datetime,
) -> EntradeMonthlyContract:
    if logical_symbol != VN30_FRONT_MONTH_SYMBOL:
        raise ValueError(f"Unsupported continuous derivative symbol: {logical_symbol}")
    if at.tzinfo is None:
        raise ValueError("Contract resolution timestamp must be timezone-aware")

    records = payload.get("data")
    if not isinstance(records, list):
        raise ValueError(  # noqa: TRY004 - preserve the adapter's payload error contract.
            "Entrade derivatives response does not contain a data list",
        )

    contracts = [
        EntradeMonthlyContract.from_payload(record)
        for record in records
        if isinstance(record, dict)
        and record.get("symbol")
        and record.get("expirationDate")
        and str(record.get("type", "")).startswith("VN30F")
    ]
    active = [
        contract
        for contract in contracts
        if contract.trading_cutoff >= at.astimezone(UTC)
    ]
    if not active:
        raise ValueError(f"No active Entrade contract found for {logical_symbol}")
    return min(active, key=lambda contract: contract.expiration)


def _parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_date(value: str) -> date:
    return _parse_utc_datetime(value).date()


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
