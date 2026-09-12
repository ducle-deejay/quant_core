# spec: 40-tests.md C — hand-computed DEC-008 conversion cases

import math

from core import AccountLimits, Instrument
from core.mapping import (
    apply_hysteresis,
    hysteresis_band_contracts,
    max_contracts_at,
    to_contracts,
)

INSTRUMENT = Instrument.load("VN30F1M")
LIMITS = AccountLimits()


def test_max_contracts_at_hand_case():
    # floor(1e8 * 0.5 / (0.05 * 1000 * 100_000)) == floor(10.0) == 10
    assert max_contracts_at(1000.0, INSTRUMENT, LIMITS) == 10


def test_to_contracts_hand_cases():
    # z at cap -> full l_max; negative symmetric; half-to-even rounding
    assert to_contracts(2.0, 1000.0, cap=2.0, instrument=INSTRUMENT, limits=LIMITS) == 10
    assert to_contracts(-2.0, 1000.0, cap=2.0, instrument=INSTRUMENT, limits=LIMITS) == -10
    # round(0.3 / 2.0 * 10) = round(1.5) == 2 (Python half-to-even)
    assert to_contracts(0.3, 1000.0, cap=2.0, instrument=INSTRUMENT, limits=LIMITS) == 2
    # non-finite z and non-positive price -> flat
    assert to_contracts(float("nan"), 1000.0, cap=2.0, instrument=INSTRUMENT, limits=LIMITS) == 0
    assert to_contracts(1.0, 0.0, cap=2.0, instrument=INSTRUMENT, limits=LIMITS) == 0
    assert to_contracts(1.0, float("nan"), cap=2.0, instrument=INSTRUMENT, limits=LIMITS) == 0


def test_to_contracts_clips_to_max_contracts():
    limits = AccountLimits(max_contracts=3)
    assert to_contracts(2.0, 1000.0, cap=2.0, instrument=INSTRUMENT, limits=limits) == 3
    assert to_contracts(-2.0, 1000.0, cap=2.0, instrument=INSTRUMENT, limits=limits) == -3


def test_hysteresis_band_contracts_hand_case():
    # max(1, round(0.35 / 2.0 * 10)) == max(1, round(1.75)) == max(1, 2) == 2
    assert hysteresis_band_contracts(0.35, 2.0, 1000.0, INSTRUMENT, LIMITS) == 2


def test_apply_hysteresis_hand_cases():
    assert apply_hysteresis(10, 8, 2) == 8    # |10-8| <= 2 -> hold
    assert apply_hysteresis(11, 8, 2) == 11   # |11-8| > 2 -> move
    assert apply_hysteresis(8, 8, 2) == 8
    assert apply_hysteresis(-10, 10, 2) == -10  # reversal always moves


def test_scaling_limits_scales_contracts():
    # doubling capital doubles the contract capacity at the same price
    doubled = AccountLimits(capital_vnd=LIMITS.capital_vnd * 2)
    assert (
        max_contracts_at(1000.0, INSTRUMENT, doubled)
        == 2 * max_contracts_at(1000.0, INSTRUMENT, LIMITS)
    )


def test_fraction_convention_documented():
    # ratio fields are fractions: the DEC-006 scalar is 0.000229 (2.29 bp)
    from core import CostModel

    cm = CostModel()
    assert cm.cost_per_side_frac == 0.000229
