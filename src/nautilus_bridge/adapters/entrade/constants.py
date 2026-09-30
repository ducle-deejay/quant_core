from __future__ import annotations

from datetime import time

VN_TZ = "Asia/Ho_Chi_Minh"
DNSE_DATA_CLIENT_NAME = "DNSE"
DNSE_EXECUTION_CLIENT_NAME = "DNSE"
DNSE_API_VERSION = "2026-07-23"
SUPPORTED_DNSE_RESOLUTIONS = frozenset(
    {"1", "3", "5", "15", "30", "60", "1H", "1D", "1W"}
)
ALLOWED_HISTORICAL_SOURCES = frozenset({"catalog", "api"})
NOT_IMPLEMENTED = "This operation is not implemented by the entrade adapter"
# The only DNSE board whose quotes and trades are published; other boards are dropped.
# Every recorded DNSE trade and quote for VN30F carries boardId G1, including continuous-session
# trades (data/raw/vietnam/dnse, 2026-08-12 to 2026-09-29).
DNSE_MAIN_BOARD = "G1"
# The 14:45 bar is the single closing-auction (ATC) print, known at 14:45 itself.
ATC_LOCAL_MINUTE = (14, 45)
# HNX continuous-matching sessions in local time; the bar watchdog only runs inside them.
CONTINUOUS_SESSIONS_LOCAL = ((time(9, 0), time(11, 30)), (time(13, 0), time(14, 30)))
