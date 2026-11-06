from __future__ import annotations

import pandas as pd

from market_data.clean import FULL_DAY_BARS
from market_data.clean import clean_day


def session(volume: float = 10.0) -> pd.DataFrame:
    morning = pd.date_range("2026-10-22 09:00", periods=150, freq="min", tz="Asia/Ho_Chi_Minh")
    afternoon = pd.date_range("2026-10-22 13:00", periods=90, freq="min", tz="Asia/Ho_Chi_Minh")
    closing = pd.DatetimeIndex([pd.Timestamp("2026-10-22 14:45", tz="Asia/Ho_Chi_Minh")])
    opens = morning.append(afternoon).append(closing).tz_convert("UTC")
    return pd.DataFrame({"timestamp": opens, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": volume})


def at(bars: pd.DataFrame, minute: str) -> pd.Series:
    return bars["timestamp"] == pd.Timestamp(f"2026-10-22 {minute}", tz="Asia/Ho_Chi_Minh").tz_convert("UTC")


def test_a_day_matching_the_brokers_is_kept():
    result = clean_day(session(), [session(), session(), session()])
    assert result.outcome == "kept"
    assert result.bars.equals(session())


def test_a_minute_lost_by_dnse_is_filled_from_the_brokers():
    dnse = session()[~at(session(), "10:15")]
    result = clean_day(dnse, [session(), session(), session()])
    assert result.outcome == "gaps_filled"
    assert len(result.bars) == FULL_DAY_BARS and len(result.filled) == 1


def test_volume_shifted_into_a_neighbour_bar_is_moved_back_and_other_bars_are_kept():
    dnse = session()
    dnse.loc[at(dnse, "10:16"), "volume"] = 20.0
    dnse.loc[at(dnse, "13:00"), "volume"] = 9.0  # one contract split across 13:00 and 13:01 unlike the brokers
    dnse.loc[at(dnse, "13:01"), "volume"] = 11.0
    dnse = dnse[~at(dnse, "10:15")]
    result = clean_day(dnse, [session(), session(), session()])
    assert result.outcome == "corrected"
    assert len(result.corrected) == 1
    assert result.bars.loc[at(result.bars, "13:00"), "volume"].item() == 9.0


def test_one_broker_out_of_line_is_outvoted():
    wrong = session()
    wrong.loc[at(wrong, "11:00"), "volume"] = 500.0
    dnse = session()[~at(session(), "10:15")]
    result = clean_day(dnse, [session(), wrong, session()])
    assert result.outcome == "gaps_filled"
    assert result.bars["volume"].sum() == session()["volume"].sum()


def test_dnse_is_kept_and_unresolved_when_the_brokers_disagree():
    dnse = session()[~at(session(), "10:15")]
    result = clean_day(dnse, [session(10.0), session(11.0), session(12.0)])
    assert result.outcome == "unresolved"
    assert result.bars.equals(dnse)
