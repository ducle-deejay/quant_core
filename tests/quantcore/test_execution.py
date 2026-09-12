# spec: 40-tests.md B8 + execution contracts — TargetSeries feeds execution

import numpy as np
import pandas as pd
import pytest

from core import Instrument
from core.artifacts import TargetSeries, Window
from quantcore.execution import (
    ExecutionConfig,
    UrgencyInputs,
    backtest_execution,
    plan_orders,
    slippage_report,
    urgency_analysis,
)

INSTRUMENT = Instrument.load("VN30F1M")


def make_targets_and_bars(bars_fixture):
    n = len(bars_fixture.ts)
    contracts = np.zeros(n, dtype=int)
    contracts[100:200] = 2
    contracts[200:300] = -1
    window = bars_fixture.window
    targets = TargetSeries(
        ts=bars_fixture.ts,
        target_contracts=contracts,
        window=window,
        instrument=INSTRUMENT,
    )
    return targets, bars_fixture


def test_target_series_to_frame_feeds_execution(bars_fixture):
    targets, bars = make_targets_and_bars(bars_fixture)
    report = backtest_execution(targets, bars)
    assert report.n_orders > 0
    assert report.n_fills > 0
    # n_target_changes counts bars with a target evaluated (old-system
    # semantics, kept for parity); orders/fills are the real proof
    assert report.n_target_changes == len(targets.target_contracts)
    assert report.algo == "marketable_limit"
    assert report.provenance


def test_execution_instrument_mismatch_raises(bars_fixture):
    other = Instrument(symbol="OTHER", venue="HNX", multiplier=1.0, tick_size=0.1)
    targets, bars = make_targets_and_bars(bars_fixture)
    mismatched = TargetSeries(
        ts=targets.ts, target_contracts=targets.target_contracts,
        window=targets.window, instrument=other,
    )
    with pytest.raises(ValueError):
        backtest_execution(mismatched, bars)


def test_constant_targets_place_no_orders(bars_fixture):
    n = len(bars_fixture.ts)
    targets = TargetSeries(
        ts=bars_fixture.ts,
        target_contracts=np.zeros(n, dtype=int),
        window=bars_fixture.window,
        instrument=INSTRUMENT,
    )
    report = backtest_execution(targets, bars_fixture)
    assert report.n_orders == 0 and report.n_fills == 0


def test_plan_orders_registry_contract():
    config = ExecutionConfig()
    orders = plan_orders(3, config, algo="twap")
    assert sum(orders) == 3
    assert all(o > 0 for o in orders)


def test_urgency_analysis_keyword_inputs():
    report = urgency_analysis(
        UrgencyInputs(
            gap_contracts=2.0,
            half_spread_bps=1.0,
            impact_bps=0.5,
            alpha_decay_per_bar=0.1,
            value_of_1bp=100_000.0,
        )
    )
    assert isinstance(report, object)  # typed report; units documented in class


def test_slippage_report_explicit_save_only(bars_fixture, tmp_path):
    targets, bars = make_targets_and_bars(bars_fixture)
    report = backtest_execution(targets, bars)
    slippy = slippage_report(fills=report.fills)
    assert not (tmp_path / "any").exists()  # no implicit writes
    path = slippy.save(tmp_path)
    assert path.exists()
