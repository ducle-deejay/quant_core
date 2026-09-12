"""Core layer: contracts, score->contracts mapping, expiry rule, artifacts.
No imports from market_data/quantcore/trading/alpha_core; stdlib+pandas+numpy only.
"""

from .artifacts import (
    DEFAULT_POOL_DIR,
    DEFAULT_RESEARCH_DIR,
    POOL_SCHEMA_VERSION,
    AlphaPool,
    Composite,
    PoolEntry,
    PoolSchemaError,
    SpecSheet,
    TargetSeries,
    TearSheet,
    WeightsArtifact,
    Window,
    append_trial_ledger,
)
from .contracts import (
    Account,
    AccountLimits,
    CostModel,
    HarnessParams,
    Instrument,
    Portfolio,
    PortfolioConfig,
    RiskAction,
    RiskConfig,
    RiskController,
    RiskDecision,
    RiskState,
    TargetPosition,
)
from .data import (
    DEFAULT_BAR_TYPE,
    DEFAULT_CATALOG_PATH,
    DEFAULT_INSTRUMENT_ID,
    BarFrame,
    CatalogClient,
    DataConfig,
)
from .expiry import (
    EXPIRY_HOUR_LOCAL,
    EXPIRY_MINUTE_LOCAL,
    VN_TZ,
    ExpiryGateDecision,
    ExpiryState,
    apply_expiry_gate,
    vn30_front_month_expiry_cutoff_utc,
    vn30_front_month_expiry_date_local,
)
from .mapping import (
    apply_hysteresis,
    hysteresis_band_contracts,
    max_contracts_at,
    to_contracts,
)
from .registry import Method, Registry
from .signal import close_returns, rolling_vol, sanitize_scores

__all__ = [
    # artifacts
    "DEFAULT_POOL_DIR",
    "DEFAULT_RESEARCH_DIR",
    "POOL_SCHEMA_VERSION",
    "AlphaPool",
    "Composite",
    "PoolEntry",
    "PoolSchemaError",
    "WindowMismatch",
    "SpecSheet",
    "TargetSeries",
    "TearSheet",
    "WeightsArtifact",
    "Window",
    "append_trial_ledger",
    # contracts
    "Account",
    "AccountLimits",
    "CostModel",
    "HarnessParams",
    "Instrument",
    "Portfolio",
    "PortfolioConfig",
    "RiskAction",
    "RiskConfig",
    "RiskDecision",
    "RiskController",
    "RiskState",
    "close_returns",
    "rolling_vol",
    "sanitize_scores",
    "TargetPosition",
    # data
    "DEFAULT_BAR_TYPE",
    "DEFAULT_CATALOG_PATH",
    "DEFAULT_INSTRUMENT_ID",
    "BarFrame",
    "CatalogClient",
    "DataConfig",
    # expiry
    "EXPIRY_HOUR_LOCAL",
    "EXPIRY_MINUTE_LOCAL",
    "VN_TZ",
    "ExpiryGateDecision",
    "ExpiryState",
    "apply_expiry_gate",
    "vn30_front_month_expiry_cutoff_utc",
    "vn30_front_month_expiry_date_local",
    # mapping
    "apply_hysteresis",
    "hysteresis_band_contracts",
    "max_contracts_at",
    "to_contracts",
    # registry
    "Method",
    "Registry",
]
