from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from nautilus_trader.model.data import BarType
from nautilus_trader.model.data import TradeTick
from nautilus_trader.model.enums import AggressorSide
from nautilus_trader.model.identifiers import TradeId
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.persistence.wranglers_v2 import OrderBookDepth10DataWranglerV2

from market_data.instruments import build_continuous_futures_contract
from market_data.instruments import build_futures_contract
from market_data.instruments import load_futures_instrument_spec
from market_data.instruments import register_futures_instrument_currency
from market_data.sources.dnse.quality import page_number
from market_data.sources.dnse.quality import read_json


BAR_TYPE = "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL"
LOCAL_TIMEZONE = "Asia/Ho_Chi_Minh"
TRADE_PAGE_BATCH_SIZE = 50
DEPTH_PAGE_BATCH_SIZE = 25
DEPTH_LEVELS = 10


def transform_day(
    *,
    raw_day: str | Path,
    instrument_config: str | Path,
) -> Iterator[list[Any]]:
    """Transform one retained DNSE ingestion into Nautilus domain objects."""
    source = Path(raw_day)
    contracts = _load_contracts(source.parent / "contracts")
    continuous, monthly = _build_instruments(instrument_config, contracts)
    yield [continuous, *monthly.values()]

    root = source / "hnx" / "futures"
    for path in sorted((root / "bars").glob("*/*.json")):
        yield _transform_bars(path, continuous)
    for directory in sorted(path for path in (root / "trades").glob("*/*") if path.is_dir()):
        instrument = monthly[f"{directory.parent.name}.HNX"]
        yield from _transform_trades(directory, instrument)
    for directory in sorted(path for path in (root / "orderbook").glob("*/*") if path.is_dir()):
        instrument = monthly[f"{directory.parent.name}.HNX"]
        yield from _transform_depth(directory, instrument)


def _load_contracts(directory: Path) -> list[dict[str, str]]:
    contracts: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.json")):
        contract = read_json(path)
        if not isinstance(contract, dict) or set(contract) != {
            "symbol",
            "isin",
            "expiration",
        }:
            raise ValueError(f"Invalid DNSE contract metadata: {path}")
        contracts.append({key: str(value) for key, value in contract.items()})
    if not contracts:
        raise ValueError(f"No DNSE contract metadata found in {directory}")
    return contracts


def _build_instruments(
    instrument_config: str | Path,
    contracts: list[dict[str, str]],
) -> tuple[Any, dict[str, Any]]:
    spec = load_futures_instrument_spec(instrument_config)
    register_futures_instrument_currency(spec)
    continuous = build_continuous_futures_contract(spec)
    monthly = {}
    for contract in contracts:
        instrument = build_futures_contract(
            spec.with_symbol(contract["symbol"]),
            activation=None,
            expiration=contract["expiration"],
            info={
                "dnse_isin": contract["isin"],
                "dnse_market_id": "DVX",
                "dnse_board_id": "G1",
            },
        )
        monthly[instrument.id.value] = instrument
    return continuous, monthly


def _transform_bars(path: Path, instrument: Any) -> list[Any]:
    payload = read_json(path)
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(payload["t"], unit="s", utc=True),
            "open": payload["o"],
            "high": payload["h"],
            "low": payload["l"],
            "close": payload["c"],
            "volume": payload["v"],
        },
    ).sort_values("timestamp", kind="stable")
    _validate_prices(frame[["open", "high", "low", "close"]].to_numpy(dtype=float), "bar")
    _validate_sizes(frame["volume"].to_numpy(dtype=float), "bar", allow_zero=True)
    return BarDataWrangler(BarType.from_str(BAR_TYPE), instrument).process(
        frame.set_index("timestamp")[["open", "high", "low", "close", "volume"]],
    )


def _transform_trades(directory: Path, instrument: Any) -> Iterator[list[TradeTick]]:
    paths = list(reversed(sorted(directory.glob("page_*.json"))))
    carry: pd.DataFrame | None = None
    for index, group in enumerate(_page_batches(paths, TRADE_PAGE_BATCH_SIZE)):
        rows: list[dict[str, object]] = []
        for path in group:
            page = page_number(path)
            for row_index, row in enumerate(read_json(path)["trades"]):
                rows.append(
                    {
                        "timestamp": row["time"],
                        "price": row["matchPrice"],
                        "quantity": row["matchQtty"],
                        "side": row["side"],
                        "trade_id": _provider_record_id(
                            directory.parent.name,
                            directory.name,
                            page,
                            row_index,
                        ),
                        "source_page": page,
                        "source_row": row_index,
                    },
                )
        frame = _normalize_trade_frame(rows)
        if carry is not None:
            frame = pd.concat([carry, frame], ignore_index=True)
        if frame.empty:
            continue
        frame = frame.sort_values(
            ["timestamp", "source_page", "source_row"],
            kind="stable",
        ).reset_index(drop=True)
        emitted, carry = _split_timestamp_boundary(
            frame,
            timestamp_column="timestamp",
            is_last=index == len(_page_batches(paths, TRADE_PAGE_BATCH_SIZE)) - 1,
        )
        if not emitted.empty:
            yield _trade_ticks(emitted, instrument)


def _normalize_trade_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "price",
                "quantity",
                "side",
                "trade_id",
                "source_page",
                "source_row",
            ],
        )
    timestamps = pd.to_datetime(frame["timestamp"], errors="raise")
    frame["timestamp"] = timestamps.dt.tz_localize(LOCAL_TIMEZONE).dt.tz_convert("UTC")
    if not frame["side"].isin(["BUY", "SELL", "UNSPECIFIED"]).all():
        raise ValueError("DNSE trade side must be BUY, SELL, or UNSPECIFIED")
    _validate_prices(frame["price"].to_numpy(dtype=float), "trade")
    _validate_sizes(frame["quantity"].to_numpy(dtype=float), "trade", allow_zero=False)
    if frame["trade_id"].duplicated().any():
        raise ValueError("Synthetic DNSE trade IDs must be unique")
    return frame


def _trade_ticks(frame: pd.DataFrame, instrument: Any) -> list[TradeTick]:
    sides = {
        "BUY": AggressorSide.BUYER,
        "SELL": AggressorSide.SELLER,
        "UNSPECIFIED": AggressorSide.NO_AGGRESSOR,
    }
    result = []
    for row in frame.itertuples(index=False):
        timestamp_value: Any = row.timestamp
        timestamp = pd.Timestamp(timestamp_value).value
        result.append(
            TradeTick(
                instrument_id=instrument.id,
                price=instrument.make_price(row.price),
                size=instrument.make_qty(row.quantity),
                aggressor_side=sides[str(row.side)],
                trade_id=TradeId(str(row.trade_id)),
                ts_event=timestamp,
                ts_init=timestamp,
            ),
        )
    return result


def _transform_depth(directory: Path, instrument: Any) -> Iterator[list[Any]]:
    paths = list(reversed(sorted(directory.glob("page_*.json"))))
    groups = _page_batches(paths, DEPTH_PAGE_BATCH_SIZE)
    carry: pd.DataFrame | None = None
    for index, group in enumerate(groups):
        rows: list[dict[str, object]] = []
        for path in group:
            page = page_number(path)
            for row_index, row in enumerate(read_json(path)["quotes"]):
                rows.append(_normalize_depth_row(row, page, row_index))
        frame = _normalize_depth_frame(rows)
        if carry is not None:
            frame = pd.concat([carry, frame], ignore_index=True)
        if frame.empty:
            continue
        frame = frame.sort_values(
            ["ts_event", "source_page", "source_row"],
            kind="stable",
        ).reset_index(drop=True)
        emitted, carry = _split_timestamp_boundary(
            frame,
            timestamp_column="ts_event",
            is_last=index == len(groups) - 1,
        )
        if not emitted.empty:
            yield OrderBookDepth10DataWranglerV2(
                instrument_id=instrument.id.value,
                price_precision=instrument.price_precision,
                size_precision=instrument.size_precision,
            ).from_pandas(emitted[_depth_columns()])


def _normalize_depth_row(
    row: dict[str, object],
    page: int,
    row_index: int,
) -> dict[str, object]:
    result: dict[str, object] = {
        "ts_event": row["time"],
        "ts_init": row["time"],
        "flags": 0,
        "sequence": 0,
        "source_page": page,
        "source_row": row_index,
    }
    bids = row.get("bid") or []
    asks = row.get("offer") or []
    if not isinstance(bids, list) or not isinstance(asks, list):
        raise ValueError("DNSE depth bid and offer fields must be arrays")
    for level in range(DEPTH_LEVELS):
        bid = bids[level] if level < len(bids) else {}
        ask = asks[level] if level < len(asks) else {}
        result[f"bid_price_{level}"] = bid.get("price", 0)
        result[f"ask_price_{level}"] = ask.get("price", 0)
        result[f"bid_size_{level}"] = bid.get("quantity", 0)
        result[f"ask_size_{level}"] = ask.get("quantity", 0)
        result[f"bid_count_{level}"] = 0
        result[f"ask_count_{level}"] = 0
    return result


def _normalize_depth_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    timestamps = pd.to_datetime(frame["ts_event"], errors="raise")
    normalized = timestamps.dt.tz_localize(LOCAL_TIMEZONE).dt.tz_convert("UTC")
    frame["ts_event"] = normalized
    frame["ts_init"] = normalized
    price_columns = [
        f"{side}_price_{level}" for side in ("bid", "ask") for level in range(DEPTH_LEVELS)
    ]
    size_columns = [
        f"{side}_size_{level}" for side in ("bid", "ask") for level in range(DEPTH_LEVELS)
    ]
    _validate_prices(frame[price_columns].to_numpy(dtype=float), "depth")
    _validate_sizes(frame[size_columns].to_numpy(dtype=float), "depth", allow_zero=True)
    return frame


def _split_timestamp_boundary(
    frame: pd.DataFrame,
    *,
    timestamp_column: str,
    is_last: bool,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    if is_last:
        return frame, None
    boundary = frame[timestamp_column].iloc[-1]
    emitted = frame.loc[frame[timestamp_column] < boundary].copy()
    carry = frame.loc[frame[timestamp_column] == boundary].copy()
    return emitted, carry


def _page_batches(paths: list[Path], size: int) -> list[list[Path]]:
    return [paths[index : index + size] for index in range(0, len(paths), size)]


def _provider_record_id(symbol: str, day: str, page: int, row: int) -> str:
    value = f"D{symbol}{day.replace('-', '')}{page:05d}{row:04d}"
    if len(value) > 36:
        raise ValueError(f"Synthetic provider-record ID exceeds Nautilus limit: {value}")
    return value


def _validate_prices(values: np.ndarray, category: str) -> None:
    if not np.isfinite(values).all() or not np.allclose(values * 10, np.round(values * 10)):
        raise ValueError(f"DNSE {category} prices do not conform to precision 1")


def _validate_sizes(values: np.ndarray, category: str, *, allow_zero: bool) -> None:
    minimum = 0 if allow_zero else 1
    if (
        not np.isfinite(values).all()
        or (values < minimum).any()
        or not np.allclose(values, np.round(values))
    ):
        raise ValueError(f"DNSE {category} sizes do not conform to precision 0")


def _depth_columns() -> list[str]:
    columns = ["ts_event", "ts_init", "flags", "sequence"]
    for field in ("bid_price", "ask_price", "bid_size", "ask_size", "bid_count", "ask_count"):
        columns.extend(f"{field}_{level}" for level in range(DEPTH_LEVELS))
    return columns
