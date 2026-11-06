from __future__ import annotations

import pandas as pd

from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1M_SESSIONS
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import TradingSessions


def session_boundary_record_mask(timestamps: pd.Series, sessions: TradingSessions) -> pd.Series:
    local = timestamps.dt.tz_convert(sessions.timezone)
    minutes = local.dt.hour * 60 + local.dt.minute
    session_ends = [end.hour * 60 + end.minute for _, end in sessions.continuous]
    return minutes.isin(session_ends)


def fold_session_boundary_timestamps(timestamps: list[int]) -> list[int]:
    """Bar open times in epoch seconds once each session-boundary record joins the preceding minute."""
    boundary = session_boundary_record_mask(pd.Series(pd.to_datetime(timestamps, unit="s", utc=True)), VN30F1M_SESSIONS)
    folded = [value - 60 if is_boundary else value for value, is_boundary in zip(timestamps, boundary, strict=True)]
    return list(dict.fromkeys(folded))


def normalize_boundary_bars(frame: pd.DataFrame, sessions: TradingSessions) -> pd.DataFrame:
    """One-minute bars with each record at a continuous session's end merged into the preceding minute, on session minutes only."""
    if frame.empty:
        return frame

    boundary_mask = session_boundary_record_mask(frame["timestamp"], sessions)
    normalized = frame.copy()
    boundary_indices: list[int] = []
    if boundary_mask.any():
        timestamp_indices = normalized.groupby("timestamp", sort=False).groups
        for index, row in normalized.loc[boundary_mask].iterrows():
            timestamp = pd.Timestamp(row["timestamp"])
            predecessor_timestamp = timestamp - pd.Timedelta(minutes=1)
            predecessor_indices = timestamp_indices.get(predecessor_timestamp, ())
            if len(predecessor_indices) == 0:
                normalized.at[index, "timestamp"] = predecessor_timestamp
                continue
            if len(predecessor_indices) != 1:
                expected_minute = predecessor_timestamp.tz_convert(
                    sessions.timezone,
                ).strftime("%H:%M")
                raise ValueError(
                    "Cannot normalize one-minute bar at "
                    f"{timestamp}: expected exactly one {expected_minute} predecessor",
                )

            predecessor_index = predecessor_indices[0]
            normalized.at[predecessor_index, "high"] = max(
                normalized.at[predecessor_index, "high"],
                row["high"],
            )
            normalized.at[predecessor_index, "low"] = min(
                normalized.at[predecessor_index, "low"],
                row["low"],
            )
            normalized.at[predecessor_index, "close"] = row["close"]
            normalized.at[predecessor_index, "volume"] += row["volume"]
            boundary_indices.append(index)

        if boundary_indices:
            normalized = normalized.drop(index=boundary_indices)

    canonical_mask = sessions.session_minute_mask(normalized["timestamp"])
    return normalized.loc[canonical_mask].reset_index(drop=True)
