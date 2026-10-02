from __future__ import annotations

import pandas as pd

from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1M_SESSIONS


def legacy_boundary_record_mask(timestamps: pd.Series) -> pd.Series:
    local = timestamps.dt.tz_convert(VN30F1M_SESSIONS.timezone)
    minutes = local.dt.hour * 60 + local.dt.minute
    session_ends = [end.hour * 60 + end.minute for _, end in VN30F1M_SESSIONS.continuous]
    return minutes.isin(session_ends)
