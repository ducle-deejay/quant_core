# spec: 40-tests.md B10/E23 — pool-derived portfolio config + limits drift

import numpy as np
import pandas as pd
import pytest

from core import AccountLimits, Instrument
from core.artifacts import AlphaPool, PoolEntry, WeightsArtifact, Window
from strategy.portfolio import portfolio_config_from_pool

INSTRUMENT = Instrument.load("VN30F1M")
W = Window(
    instrument_id="VN30F1M.HNX",
    bar_type="1-MINUTE-LAST-EXTERNAL",
    start=pd.Timestamp("2026-06-01", tz="UTC"),
    end=pd.Timestamp("2026-06-05", tz="UTC"),
    n_bars=100,
)


def make_pool():
    pool = AlphaPool(instrument="VN30F1M")
    for aid, window in (("a1", 2), ("a2", 5)):
        pool.add(PoolEntry(alpha_id=aid, dsl=f"ts_returns(close, {window})"))
    return pool


def test_portfolio_config_from_pool(tmp_path):
    pool = make_pool()
    artifact = WeightsArtifact(
        generated="2026-09-12T00:00:00+00:00",
        method="inverse_vol",
        weights={"a1": 0.75, "a2": 0.25},
        window=W,
    )
    config = portfolio_config_from_pool(artifact, pool, INSTRUMENT)
    # alpha_id weights must join through the pool into DSL expressions
    assert set(config.expressions) == {"ts_returns(close, 2)", "ts_returns(close, 5)"}
    assert sum(config.weights) == pytest.approx(1.0, abs=1e-12)
    assert config.limits.capital_vnd == AccountLimits().capital_vnd


def test_portfolio_config_weight_key_without_pool_entry():
    artifact = WeightsArtifact(
        generated="x", method="m", weights={"ghost_alpha": 1.0}, window=W,
    )
    with pytest.raises(ValueError, match="absent from pool"):
        portfolio_config_from_pool(artifact, make_pool(), INSTRUMENT)


def test_missing_weights_file_fails_clearly(tmp_path):
    with pytest.raises(Exception, match="weights"):
        WeightsArtifact.load(tmp_path)


def test_instrument_mismatch_rejected(tmp_path):
    pool = make_pool()
    artifact = WeightsArtifact(
        generated="x", method="m", weights={"a1": 1.0, "a2": 0.0},
        window=Window(
            instrument_id="OTHER.HNX", bar_type="b",
            start=pd.Timestamp("2026-06-01", tz="UTC"),
            end=pd.Timestamp("2026-06-05", tz="UTC"), n_bars=100,
        ),
    )
    with pytest.raises(ValueError):
        portfolio_config_from_pool(artifact, pool, INSTRUMENT)


def test_capital_drift_moves_research_targets():
    """Doubling limits.capital_vnd must scale research-side capacity (B10)."""
    from core.mapping import max_contracts_at

    # price 1000 makes l_max exact (10 and 20) so the 2x comparison skips
    # the floor nonlinearity
    base = max_contracts_at(1000.0, INSTRUMENT, AccountLimits())
    doubled = max_contracts_at(1000.0, INSTRUMENT, AccountLimits(capital_vnd=200_000_000.0))
    assert (base, doubled) == (10, 20)
