"""quantcore - Python bindings for the alpha-core quantitative engine.

Rust engine exposed via PyO3. Primary entry points:

    canonical_map_py(score, span, z_window, band, cap, bars_per_day)
    compute_pnl_py(pos, ret, cost_per_side, bars_per_day)
"""
from .quantcore import (
    PyCanonicalResult,
    PyPnlResult,
    canonical_map_py,
    compute_pnl_py,
)

__all__ = [
    "PyCanonicalResult",
    "PyPnlResult",
    "canonical_map_py",
    "compute_pnl_py",
]
__version__ = "0.1.0"
