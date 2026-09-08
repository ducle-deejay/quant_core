"""Market-data access for the API (DEC-017).

The research catalog stores Nautilus-parquet bars. The OHLCV columns are
Nautilus's internal byte encoding, so bars are decoded through
``ParquetDataCatalog`` (never ``pd.read_parquet`` directly - verified
2026-09-01: pandas returns bytes objects for open/high/low/close/volume).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from quantcore.core.config import DEFAULT_CATALOG_PATH, DataConfig


def load_bars(config: DataConfig | None = None) -> pd.DataFrame:
    """Load OHLCV bars from the research catalog into a DataFrame.

    Columns: ``ts`` (UTC datetime, sorted), ``open``, ``high``, ``low``,
    ``close``, ``volume`` (floats). With the default config this is the full
    VN30F1M 1-minute history.
    """
    cfg = config or DataConfig()
    catalog_path = Path(cfg.catalog_path) if cfg.catalog_path else DEFAULT_CATALOG_PATH
    if not catalog_path.exists():
        raise FileNotFoundError(f"research catalog not found at {catalog_path}")
    catalog = ParquetDataCatalog(str(catalog_path))
    start = pd.Timestamp(cfg.start, tz="UTC") if cfg.start else None
    end = pd.Timestamp(cfg.end, tz="UTC") if cfg.end else None
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
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    return df.sort_values("ts").reset_index(drop=True)


def close_volume(df: pd.DataFrame) -> tuple[list[float], list[float]]:
    """Extract engine-ready ``close``/``volume`` lists from a bars frame."""
    return (
        df["close"].astype(float).tolist(),
        df["volume"].astype(float).tolist(),
    )
