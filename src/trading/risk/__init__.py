"""Component 7 risk overlay package (live wiring phase, workstream C).

Exposes the pure core (``RiskConfig``, ``RiskLedger``, session helpers,
status/reason vocabulary) and the thin Nautilus v1 integration
(``RiskOverlayActor``, ``RiskOverlayConfig``). The contract types
``RiskState``/``TargetPosition`` live in ``trading.contracts`` (single
contract file joining the three workstreams, decision DEC-008).
"""

from trading.risk.overlay import RiskOverlayActor, RiskOverlayConfig
from trading.risk.state import (
    ACTIVE,
    HALTED,
    REDUCING,
    REASON_EXCEEDS_MAX,
    REASON_EXPOSURE,
    REASON_LOSS,
    REASON_REDUCING_ONLY,
    REASON_STALE,
    RiskConfig,
    RiskLedger,
    is_session_open,
    session_day,
)

__all__ = [
    "ACTIVE",
    "HALTED",
    "REDUCING",
    "REASON_EXCEEDS_MAX",
    "REASON_EXPOSURE",
    "REASON_LOSS",
    "REASON_REDUCING_ONLY",
    "REASON_STALE",
    "RiskConfig",
    "RiskLedger",
    "RiskOverlayActor",
    "RiskOverlayConfig",
    "is_session_open",
    "session_day",
]
