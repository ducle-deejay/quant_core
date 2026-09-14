from __future__ import annotations

VN_TZ = "Asia/Ho_Chi_Minh"
DNSE_DATA_CLIENT_NAME = "DNSE"
DNSE_EXECUTION_CLIENT_NAME = "DNSE"
DNSE_API_VERSION = "2026-07-23"
SUPPORTED_DNSE_RESOLUTIONS = frozenset(
    {"1", "3", "5", "15", "30", "60", "1H", "1D", "1W"}
)
ALLOWED_HISTORICAL_SOURCES = frozenset({"catalog", "api"})
NOT_IMPLEMENTED = "This operation is not implemented by the entrade_template adapter"
