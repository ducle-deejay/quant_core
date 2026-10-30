from __future__ import annotations

import pandas as pd

from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1M_SESSIONS


def session_boundary_record_mask(timestamps: pd.Series) -> pd.Series:
    local = timestamps.dt.tz_convert(VN30F1M_SESSIONS.timezone)
    minutes = local.dt.hour * 60 + local.dt.minute
    session_ends = [end.hour * 60 + end.minute for _, end in VN30F1M_SESSIONS.continuous]
    return minutes.isin(session_ends)


def fold_session_boundary_timestamps(timestamps: list[int]) -> list[int]:
    """Bar open times in epoch seconds once each session-boundary record joins the preceding minute."""
    boundary = session_boundary_record_mask(pd.Series(pd.to_datetime(timestamps, unit="s", utc=True)))
    folded = [value - 60 if is_boundary else value for value, is_boundary in zip(timestamps, boundary, strict=True)]
    return list(dict.fromkeys(folded))
