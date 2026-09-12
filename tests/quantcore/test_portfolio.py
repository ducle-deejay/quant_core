# spec: 40-tests.md B6/B9 — portfolio contracts (window guard, registry dispatch)

import numpy as np
import pandas as pd
import pytest

from core.artifacts import Window, WindowMismatch
from quantcore.portfolio import combine, combine_methods


def make_window(n, offset_days=0):
    return Window(
        instrument_id="VN30F1M.HNX",
        bar_type="1-MINUTE-LAST-EXTERNAL",
        start=pd.Timestamp("2026-06-01", tz="UTC") + pd.Timedelta(days=offset_days),
        end=pd.Timestamp("2026-06-02", tz="UTC") + pd.Timedelta(days=offset_days),
        n_bars=n,
    )


def make_scores(n=10):
    rng = np.random.default_rng(7)  # deterministic test input, NOT market data
    return {
        "a": np.sin(np.linspace(0, 3, n)),
        "b": np.cos(np.linspace(0, 3, n)),
    }


def test_combine_requires_window():
    with pytest.raises(TypeError):
        combine(make_scores())


def test_combine_carries_window_provenance():
    window = make_window(10)
    composite = combine(make_scores(), window=window)
    assert composite.window is window
    assert composite.method == "inverse_vol"


def test_registry_dispatch_is_real():
    """Replacing the registered inverse_vol must change combine output."""
    scores = make_scores()
    baseline = combine(dict(scores), window=make_window(10))

    original = combine_methods.get("inverse_vol")

    def constant_method(scores_dict):
        arr = np.ones(len(next(iter(scores_dict.values()))))
        return arr * 0.5, {name: 1.0 / len(scores_dict) for name in scores_dict}

    try:
        combine_methods.register(
            "inverse_vol", constant_method, source="python", replace=True
        )
        overridden = combine(dict(scores), window=make_window(10))
    finally:
        combine_methods.register(
            "inverse_vol", original.fn, source=original.source, replace=True
        )

    assert not np.allclose(baseline.scores, overridden.scores)
    # restored dispatch returns the baseline behavior
    restored = combine(dict(scores), window=make_window(10))
    assert np.allclose(baseline.scores, restored.scores)


def test_explicit_weights_label():
    composite = combine(
        {"a": np.ones(5), "b": np.ones(5)},
        weights={"a": 3.0, "b": 1.0},
        window=make_window(5),
    )
    assert composite.method == "explicit"
    assert composite.weights == (0.75, 0.25)
