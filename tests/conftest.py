"""Shared fixtures — REAL data only (spec: 40-tests.md)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:  # direct runs without uv sync
    sys.path.insert(0, str(SRC))

FIXTURES = REPO / "tmp" / "fixtures"
GOLDENS = REPO / "tmp" / "golden" / "goldens.json"


@pytest.fixture(scope="session")
def bars_fixture_df() -> pd.DataFrame:
    return pd.read_parquet(FIXTURES / "bars_20260601_20260911.parquet")


@pytest.fixture(scope="session")
def bars_fixture(bars_fixture_df):
    from core.data import DEFAULT_BAR_TYPE, DEFAULT_INSTRUMENT_ID, BarFrame

    return BarFrame.from_dataframe(
        bars_fixture_df,
        instrument_id=DEFAULT_INSTRUMENT_ID,
        bar_type=DEFAULT_BAR_TYPE,
    )


@pytest.fixture(scope="session")
def goldens() -> dict:
    return __import__("json").loads(GOLDENS.read_text())


@pytest.fixture(scope="session")
def full_bars():
    from core.data import CatalogClient, DataConfig

    return CatalogClient().bars(DataConfig())
