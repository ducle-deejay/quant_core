"""alpha_core - Python bindings for the alpha-core quantitative engine.

Rust engine exposed via PyO3 (pyo3 0.29). Every pipeline stage is callable
from Python; the Rust public API remains the engine-side surface.

Quick start::

    import alpha_core as q

    pos = q.canonical_map_py(score, span=8, z_window=480,
                             band=0.35, cap=2.0, bars_per_day=240)
    pnl = q.compute_pnl_py(pos.position, returns,
                           cost_per_side=0.0001, bars_per_day=240)
    rows = q.ic_ladder_py(score, returns, horizons=[1, 3, 8],
                          window=480, bars_per_day=240)
"""
from .alpha_core import (
    # Component 1 - canonical simulation
    PyCanonicalResult,
    PyPnlResult,
    canonical_map_py,
    compute_pnl_py,
    # Component 1 - metrics
    max_drawdown_py,
    sharpe_py,
    # Component 2 - evaluation and screening
    PyBlockStats,
    PyIcResult,
    PyScreeningOutcome,
    PyWalkForwardResult,
    deflated_sharpe_probability_py,
    deflated_threshold_py,
    ic_ladder_py,
    rank_survivors_py,
    screen_candidates_py,
    walk_forward_py,
    # Component 0 - mining
    execute_batch_py,
    ga_best_expression_py,
    ga_breed_py,
    validate_expression_py,
    # Components 3-5 - portfolio construction and sizing
    composite_score_py,
    drawdown_multiplier_py,
    inverse_vol_combine_py,
    orthogonalize_py,
    vol_target_py,
)

__all__ = [
    "PyBlockStats",
    "PyCanonicalResult",
    "PyIcResult",
    "PyPnlResult",
    "PyScreeningOutcome",
    "PyWalkForwardResult",
    "canonical_map_py",
    "composite_score_py",
    "compute_pnl_py",
    "deflated_sharpe_probability_py",
    "deflated_threshold_py",
    "drawdown_multiplier_py",
    "execute_batch_py",
    "ga_best_expression_py",
    "ga_breed_py",
    "ic_ladder_py",
    "inverse_vol_combine_py",
    "max_drawdown_py",
    "orthogonalize_py",
    "rank_survivors_py",
    "screen_candidates_py",
    "sharpe_py",
    "validate_expression_py",
    "vol_target_py",
    "walk_forward_py",
]
__version__ = "0.1.0"
