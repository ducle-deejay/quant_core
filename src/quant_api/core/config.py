"""API-level configuration objects (DEC-017).

Reuses the milestone wiring contracts from ``trading.contracts`` and
``trading.risk.state`` so research and live configuration never drift
(parity by construction); role-specific configs live in the role modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trading.contracts import HarnessParams, PortfolioConfig  # noqa: F401
from trading.risk.state import RiskConfig  # noqa: F401

#: Catalog key for the default instrument/resolution (research catalog).
DEFAULT_BAR_TYPE = "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL"

#: Repository root (src/quant_api/core/config.py -> parents[3]).
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Default research catalog root.
DEFAULT_CATALOG_PATH = REPO_ROOT / "data" / "catalog"


@dataclass(frozen=True)
class DataConfig:
    """Data resolution for every module entry point.

    All fields optional: ``None`` means the API default (full VN30F1M
    1-minute history from the repo research catalog), so users never pass
    data manually (DEC-017).
    """

    instrument: str = "VN30F1M"
    bar_type: str = DEFAULT_BAR_TYPE
    catalog_path: str | None = None  # None -> <repo>/data/catalog
    start: str | None = None  # ISO date, e.g. "2026-01-01"; None = full history
    end: str | None = None
