import ast

import numpy as np
import pandas as pd
import pytest

from methodica.alpha_miner import canonical_form, evolve, negate, random_expression, tree_depth
from methodica.dsl import compute


@pytest.fixture
def bars():
    rng = np.random.default_rng(0)
    close = 1_000 + rng.normal(size=500).cumsum()
    spread = rng.uniform(0.1, 1.0, size=500)
    return pd.DataFrame({
        "open": close + rng.normal(scale=0.2, size=500),
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": rng.integers(1, 100, size=500).astype(float),
    }, index=pd.date_range("2021-01-04 02:00", periods=500, freq="min", tz="UTC"))


def test_random_expression_is_valid_dsl(bars):
    rng = np.random.default_rng(1)
    for _ in range(200):
        result = compute(ast.unparse(random_expression(3, list(bars.columns), rng)), bars)
        assert len(result) == len(bars)


def test_evolve_is_reproducible_with_same_seed(bars):
    first = evolve(bars, population=20, top_k=5, seed=7)
    second = evolve(bars, population=20, top_k=5, seed=7)

    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 5
    assert (first.ic >= 0).all()


def test_evolve_with_constant_seeds_yields_valid_dsl(bars):
    seeds = [
        "(ewma(close, 12) - ewma(close, 26) - ewma(ewma(close, 12) - ewma(close, 26), 9)) / ewm_std(ts_delta(close, 1), 26)",
        "(close - ts_min(low, 40)) / (ts_max(high, 40) - ts_min(low, 40)) - 0.5",
        "-ewma((2 * close - high - low) / (high - low + 0.1), 5)",
    ]
    result = evolve(bars, seeds=seeds, population=20, top_k=20, seed=0)

    assert len(result) == 20
    for expression in result.expression:
        compute(expression, bars)


def _canonical(expression):
    return ast.unparse(canonical_form(ast.parse(expression, mode="eval")))


@pytest.mark.parametrize(
    ("expression", "equivalent"),
    [
        ("--close", "close"),
        ("-ts_mean(close, 5)", "ts_mean(close, 5)"),
        ("-(-ts_mean(-(-close), 5))", "ts_mean(close, 5)"),
        ("ewma(---close, 5)", "ewma(-close, 5)"),
        ("-open / ts_std(close, 40)", "open / ts_std(close, 40)"),
        ("ewma(open / -volume, 5)", "ewma(-(open / volume), 5)"),
        ("volume * close", "close * volume"),
        ("(high * low) * close", "close * (low * high)"),
        ("ewma((-high) * low * close, 5)", "ewma(-(close * high * low), 5)"),
        ("(high + low) + (close + open)", "open + (close + (low + high))"),
        ("close - volume", "volume - close"),
        ("close - -volume", "close + volume"),
        ("-close - volume", "close + volume"),
        ("0.5 - -(close / volume)", "close / volume + 0.5"),
        ("(ewma(open, 100) - low) / ts_std(close, 20)", "(low - ewma(open, 100)) / ts_std(close, 20)"),
    ],
)
def test_canonical_form_merges_algebraically_equal_expressions(expression, equivalent):
    assert _canonical(expression) == _canonical(equivalent)


@pytest.mark.parametrize(
    ("expression", "different"),
    [
        ("close / volume", "volume / close"),
        ("(close - volume) + high", "(volume - close) + high"),
        ("ewma(close, 5) + volume", "ewma(close + volume, 5)"),
    ],
)
def test_canonical_form_keeps_different_expressions_apart(expression, different):
    assert _canonical(expression) != _canonical(different)


@pytest.mark.parametrize(
    ("expression", "negated"),
    [
        ("close - open", "open - close"),
        (
            "(ewma(close, 100) - ewma(close, 50)) / ts_max(volume, 20)",
            "(ewma(close, 50) - ewma(close, 100)) / ts_max(volume, 20)",
        ),
        ("close / ts_std(close, 20)", "-close / ts_std(close, 20)"),
        ("-close * volume", "close * volume"),
        ("ewma(close, 5)", "-ewma(close, 5)"),
        ("close + volume", "-(close + volume)"),
    ],
)
def test_negate_pushes_the_sign_inside(expression, negated):
    assert ast.unparse(negate(ast.parse(expression, mode="eval"))) == negated


def test_canonical_form_does_not_deepen_the_tree():
    tree = ast.parse("(-close) * ts_mean(ts_std(volume, 5), 20) * (high * (low * open))", mode="eval")
    assert tree_depth(canonical_form(tree)) <= tree_depth(tree)
