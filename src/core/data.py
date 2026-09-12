"""Market-data access for every role (catalog -> BarFrame / ticks / depth)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .artifacts import Window

#: Default research catalog root (override with QUANTCORE_CATALOG).
DEFAULT_CATALOG_PATH = Path(
    os.environ.get("QUANTCORE_CATALOG", "/Users/ducle/repos/nox_system/data/catalog")
)

#: Catalog key for the default instrument/resolution.
DEFAULT_BAR_TYPE = "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL"

#: Nautilus instrument id of the default instrument.
DEFAULT_INSTRUMENT_ID = "VN30F1M.HNX"

__all__ = [
    "DEFAULT_BAR_TYPE",
    "DEFAULT_CATALOG_PATH",
    "DEFAULT_INSTRUMENT_ID",
    "BarFrame",
    "CatalogClient",
    "DataConfig",
]


@dataclass(frozen=True)
class DataConfig:
    """Data resolution for every module entry point.

    All fields optional: ``None`` dates mean full history for the default
    instrument/bar type.
    """

    instrument_id: str = DEFAULT_INSTRUMENT_ID
    bar_type: str = DEFAULT_BAR_TYPE
    start: str | None = None  # ISO; None = full history
    end: str | None = None


@dataclass(frozen=True)
class BarFrame:
    """One instrument's OHLCV bars, aligned and validated.

    Attributes
    ----------
    ts : pandas.DatetimeIndex
        UTC timestamps, sorted ascending.
    open, high, low, close, volume : numpy.ndarray
        float64 OHLCV columns.
    instrument_id : str
        Nautilus instrument id the bars belong to.
    bar_type : str
        Nautilus bar type string of the bars.
    """

    ts: pd.DatetimeIndex
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    instrument_id: str
    bar_type: str

    @property
    def window(self) -> Window:
        """The Window covered by this frame (first/last ts, bar count)."""
        return Window(
            instrument_id=self.instrument_id,
            bar_type=self.bar_type,
            start=self.ts[0],
            end=self.ts[-1],
            n_bars=int(len(self.ts)),
        )

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        *,
        instrument_id: str = "",
        bar_type: str = "",
    ) -> "BarFrame":
        """Build from a DataFrame with columns ts, open, high, low, close, volume.

        Parameters
        ----------
        df : pandas.DataFrame
            Bars; ``ts`` must be timezone-aware and sorted ascending. Any
            timezone is accepted and normalized to UTC.

        Returns
        -------
        BarFrame
            The validated frame with float64 arrays. ``instrument_id`` and
            ``bar_type`` are left empty (the DataFrame carries no identity);
            pass them via the constructor when known.

        Raises
        ------
        ValueError
            If required columns are missing, the frame is empty, ``ts`` is
            timezone-naive, or ``ts`` is unsorted.
        """
        required = ["ts", "open", "high", "low", "close", "volume"]
        missing = [column for column in required if column not in df.columns]
        if missing:
            raise ValueError(f"bars dataframe missing columns: {missing}")
        if df.empty:
            raise ValueError("bars dataframe is empty")
        ts = pd.DatetimeIndex(df["ts"])
        if ts.tz is None:
            raise ValueError("ts must be timezone-aware")
        ts = ts.tz_convert("UTC")
        if not ts.is_monotonic_increasing:
            raise ValueError("ts must be sorted ascending")
        return cls(
            ts=ts,
            open=df["open"].to_numpy(dtype=np.float64),
            high=df["high"].to_numpy(dtype=np.float64),
            low=df["low"].to_numpy(dtype=np.float64),
            close=df["close"].to_numpy(dtype=np.float64),
            volume=df["volume"].to_numpy(dtype=np.float64),
            instrument_id=instrument_id,
            bar_type=bar_type,
        )

    def close_list(self) -> list[float]:
        """Return the close column as a list of floats (engine feeders)."""
        return self.close.tolist()

    def volume_list(self) -> list[float]:
        """Return the volume column as a list of floats (engine feeders)."""
        return self.volume.tolist()


class CatalogClient:
    """Read-only accessor for the Nautilus parquet research catalog.

    ``nautilus_trader`` is imported lazily inside methods only, so the rest
    of ``core`` stays importable without it.

    Parameters
    ----------
    root : pathlib.Path | None
        Catalog root; ``None`` uses :data:`DEFAULT_CATALOG_PATH`.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else DEFAULT_CATALOG_PATH

    @property
    def root(self) -> Path:
        """The catalog root this client reads from."""
        return self._root

    def bars(self, config: DataConfig | None = None) -> BarFrame:
        """Load one instrument's OHLCV bars as a validated BarFrame.

        Parameters
        ----------
        config : DataConfig | None
            Instrument/bar-type/date resolution; ``None`` uses the defaults
            (full VN30F1M 1-minute history).

        Returns
        -------
        BarFrame
            Bars sorted ascending with UTC timestamps.

        Raises
        ------
        FileNotFoundError
            If the catalog root does not exist.
        ValueError
            If the catalog returns no bars in range.

        Notes
        -----
        Bars are decoded through ``ParquetDataCatalog`` (never
        ``pd.read_parquet`` directly — pandas returns bytes objects for the
        Nautilus-encoded open/high/low/close/volume columns).
        """
        from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

        cfg = config or DataConfig()
        if not self._root.exists():
            raise FileNotFoundError(f"research catalog not found at {self._root}")
        catalog = ParquetDataCatalog(str(self._root))
        start = _as_utc_timestamp(cfg.start) if cfg.start else None
        end = _as_utc_timestamp(cfg.end) if cfg.end else None
        bars = catalog.bars(bar_types=[cfg.bar_type], start=start, end=end)
        rows = [
            {
                "ts": pd.Timestamp(bar.ts_event, unit="ns", tz="UTC"),
                "open": float(bar.open.as_double()),
                "high": float(bar.high.as_double()),
                "low": float(bar.low.as_double()),
                "close": float(bar.close.as_double()),
                "volume": float(bar.volume.as_double()),
            }
            for bar in bars
        ]
        if not rows:
            raise ValueError(
                f"no bars for {cfg.bar_type} in [{cfg.start}, {cfg.end}] at {self._root}"
            )
        df = pd.DataFrame(
            rows, columns=["ts", "open", "high", "low", "close", "volume"]
        ).sort_values("ts").reset_index(drop=True)
        return BarFrame(
            ts=pd.DatetimeIndex(df["ts"]),
            open=df["open"].to_numpy(dtype=np.float64),
            high=df["high"].to_numpy(dtype=np.float64),
            low=df["low"].to_numpy(dtype=np.float64),
            close=df["close"].to_numpy(dtype=np.float64),
            volume=df["volume"].to_numpy(dtype=np.float64),
            instrument_id=cfg.instrument_id,
            bar_type=cfg.bar_type,
        )

    def ticks(
        self,
        instrument_id: str,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """Load trade ticks as a DataFrame.

        Parameters
        ----------
        instrument_id : str
            Nautilus instrument id, e.g. ``"VN30F1M.HNX"``.
        start : str | pandas.Timestamp | None
            Inclusive range start (ISO string or timestamp); ``None`` = open.
        end : str | pandas.Timestamp | None
            Inclusive range end; ``None`` = unbounded.

        Returns
        -------
        pandas.DataFrame
            Columns ``ts`` (UTC), ``price`` (float), ``size`` (float) and
            ``aggressor_side`` (Nautilus AggressorSide name: "BUYER",
            "SELLER" or "NO_AGGRESSOR"), sorted by ``ts``.

        Raises
        ------
        FileNotFoundError
            If the catalog root does not exist.
        """
        from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

        if not self._root.exists():
            raise FileNotFoundError(f"research catalog not found at {self._root}")
        catalog = ParquetDataCatalog(str(self._root))
        trade_ticks = catalog.trade_ticks(
            instrument_ids=[instrument_id],
            start=_as_utc_timestamp(start) if start is not None else None,
            end=_as_utc_timestamp(end) if end is not None else None,
        )
        rows = [
            {
                "ts": pd.Timestamp(tick.ts_event, unit="ns", tz="UTC"),
                "price": float(tick.price.as_double()),
                "size": float(tick.size.as_double()),
                "aggressor_side": tick.aggressor_side.name,
            }
            for tick in trade_ticks
            if str(tick.instrument_id) == instrument_id
        ]
        df = pd.DataFrame(rows, columns=["ts", "price", "size", "aggressor_side"])
        return df.sort_values("ts").reset_index(drop=True)

    def depth(
        self,
        instrument_id: str,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """Load 10-level order-book depth as a long-format DataFrame.

        Parameters
        ----------
        instrument_id : str
            Nautilus instrument id, e.g. ``"VN30F1M.HNX"``.
        start : str | pandas.Timestamp | None
            Inclusive range start (ISO string or timestamp); ``None`` = open.
        end : str | pandas.Timestamp | None
            Inclusive range end; ``None`` = unbounded.

        Returns
        -------
        pandas.DataFrame
            Long format with columns ``ts`` (UTC), ``level`` (int 0-9,
            0 = best), ``side`` ("bid" | "ask"), ``price`` (float),
            ``size`` (float), sorted by ``ts``.

        Raises
        ------
        FileNotFoundError
            If the catalog root does not exist.
        """
        from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

        if not self._root.exists():
            raise FileNotFoundError(f"research catalog not found at {self._root}")
        catalog = ParquetDataCatalog(str(self._root))
        depth10 = catalog.order_book_depth10(
            instrument_ids=[instrument_id],
            start=_as_utc_timestamp(start) if start is not None else None,
            end=_as_utc_timestamp(end) if end is not None else None,
        )
        rows: list[dict] = []
        for event in depth10:
            if str(event.instrument_id) != instrument_id:
                continue
            ts = pd.Timestamp(event.ts_event, unit="ns", tz="UTC")
            for level, order in enumerate(event.bids):
                rows.append(
                    {
                        "ts": ts,
                        "level": level,
                        "side": "bid",
                        "price": float(order.price.as_double()),
                        "size": float(order.size.as_double()),
                    }
                )
            for level, order in enumerate(event.asks):
                rows.append(
                    {
                        "ts": ts,
                        "level": level,
                        "side": "ask",
                        "price": float(order.price.as_double()),
                        "size": float(order.size.as_double()),
                    }
                )
        df = pd.DataFrame(rows, columns=["ts", "level", "side", "price", "size"])
        return df.sort_values("ts", kind="stable").reset_index(drop=True)


def _as_utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    """Coerce an ISO string or timestamp to a UTC pandas.Timestamp."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")
