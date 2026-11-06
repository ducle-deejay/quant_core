"""Gap fill and correction of one day of DNSE one-minute bars against the reference brokers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from dataclasses import field

import pandas as pd


PRICES = ("open", "high", "low", "close")
FIELDS = (*PRICES, "volume")
# Agreed in docs/data_validation/vn30f1m: DNSE matches the exchange volume to the contract on a normal
# day, while daily open, high and low often differ by up to 1 point with no error
VOLUME_TOLERANCE = 0
PRICE_TOLERANCE = 1.0
MAJORITY = 2  # brokers that must agree on a value
FULL_DAY_BARS = 241  # 09:00-11:29, 13:00-14:29 and the 14:45 closing auction


@dataclass(frozen=True)
class CleanResult:
    """``outcome`` is kept, gaps_filled, corrected or unresolved; an unresolved day keeps the DNSE bars."""

    bars: pd.DataFrame
    outcome: str
    filled: tuple[pd.Timestamp, ...] = ()
    corrected: tuple[pd.Timestamp, ...] = ()
    reason: str = ""
    broker_summary: dict[str, float | None] = field(default_factory=dict)


def day_summary(bars: pd.DataFrame) -> dict[str, float]:
    ordered = bars.sort_values("timestamp")
    return {
        "open": float(ordered["open"].iloc[0]),
        "high": float(ordered["high"].max()),
        "low": float(ordered["low"].min()),
        "close": float(ordered["close"].iloc[-1]),
        "volume": float(ordered["volume"].sum()),
    }


def summary_gaps(summary: dict[str, float], expected: dict[str, float | None]) -> dict[str, int | float]:
    """Summary minus expected for each field beyond its tolerance; a field without an expected value is not compared."""
    gaps = {}
    for name in FIELDS:
        if expected.get(name) is None:
            continue
        gap = summary[name] - float(expected[name])
        gap = int(gap) if name == "volume" else round(gap, 1)  # prices carry one decimal; rounding drops float noise
        if abs(gap) > (VOLUME_TOLERANCE if name == "volume" else PRICE_TOLERANCE):
            gaps[name] = gap
    return gaps


def clean_day(dnse: pd.DataFrame, broker_bars: list[pd.DataFrame]) -> CleanResult:
    """Keep, gap-fill or correct DNSE bars so the day matches the brokers' majority daily summary."""
    available = [bars for bars in broker_bars if not bars.empty]
    broker_summary = {name: _majority([day_summary(bars)[name] for bars in available]) for name in FIELDS}
    if broker_summary["volume"] is None:
        return CleanResult(dnse, "unresolved", reason="no broker majority on daily volume", broker_summary=broker_summary)
    if len(dnse) == FULL_DAY_BARS and not summary_gaps(day_summary(dnse), broker_summary):
        return CleanResult(dnse, "kept", broker_summary=broker_summary)

    minute_majority = _minute_majority(available)
    present = set(dnse["timestamp"])
    gaps = minute_majority[~minute_majority["timestamp"].isin(present)]
    filled = pd.concat([dnse, gaps], ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    filled_times = tuple(gaps["timestamp"])
    if not filled.empty and not summary_gaps(day_summary(filled), broker_summary):
        return CleanResult(filled, "gaps_filled" if filled_times else "kept", filled=filled_times, broker_summary=broker_summary)

    merged = filled.merge(minute_majority, on="timestamp", how="left", suffixes=("", "_majority"))
    majority_values = merged[[f"{name}_majority" for name in FIELDS]].to_numpy()
    differs = merged["open_majority"].notna().to_numpy() & (merged[list(FIELDS)].to_numpy() != majority_values).any(axis=1)
    # The broker majority of a minute is not a ground truth, so only the bars needed are replaced: first those
    # next to a filled minute, where DNSE shifts a lost minute's volume (docs/data_validation/vn30f1m)
    neighbours = filled["timestamp"].isin(
        {timestamp + pd.Timedelta(minutes=step) for timestamp in filled_times for step in (-1, 1)},
    ).to_numpy()
    for replace in (differs & neighbours, differs):
        if not replace.any():
            continue
        corrected = filled.copy()
        corrected.loc[replace, list(FIELDS)] = majority_values[replace]
        if not summary_gaps(day_summary(corrected), broker_summary):
            corrected_times = tuple(corrected.loc[replace, "timestamp"])
            return CleanResult(corrected, "corrected", filled=filled_times, corrected=corrected_times, broker_summary=broker_summary)
    return CleanResult(dnse, "unresolved", reason="no gap fill or correction matches the brokers' daily summary", broker_summary=broker_summary)


def _majority(values: list[float]) -> float | None:
    if not values:
        return None
    value, count = Counter(values).most_common(1)[0]
    return value if count >= MAJORITY else None


def _minute_majority(broker_bars: list[pd.DataFrame]) -> pd.DataFrame:
    """Minutes on which a broker majority agrees on every field."""
    stacked = pd.concat(broker_bars, ignore_index=True)
    rows = []
    for timestamp, group in stacked.groupby("timestamp"):
        values = {name: _majority(group[name].tolist()) for name in FIELDS}
        if all(value is not None for value in values.values()):
            rows.append({"timestamp": timestamp, **values})
    return pd.DataFrame(rows, columns=["timestamp", *FIELDS])
