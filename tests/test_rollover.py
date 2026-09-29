"""Behaviour of the VN30 futures expiry calendar and the strategy rollover hook."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from nautilus_bridge.instruments.derivatives.futures.vn30f1m import vn30f_expiry_date
from nautilus_bridge.strategies.rollover import FuturesRollover
from nautilus_bridge.strategies.rollover import RollAction


def _ns(local: str) -> int:
    return pd.Timestamp(local, tz="Asia/Ho_Chi_Minh").tz_convert("UTC").value


@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [
        (2026, 9, date(2026, 9, 17)),
        (2026, 10, date(2026, 10, 15)),  # the 1st is a Thursday
        (2026, 12, date(2026, 12, 17)),
    ],
)
def test_expiry_is_the_third_thursday(year: int, month: int, expected: date) -> None:
    assert vn30f_expiry_date(year, month) == expected


def test_expiry_on_a_holiday_moves_to_the_previous_trading_day() -> None:
    holidays = {date(2026, 9, 17)}

    assert vn30f_expiry_date(
        2026, 9, lambda day: day.weekday() < 5 and day not in holidays
    ) == date(2026, 9, 16)


def test_roll_closes_at_14_on_expiry_day_and_reopens_on_the_next_session() -> None:
    rollover = FuturesRollover()
    bars = [
        "2026-09-16 14:00",  # day before expiry: nothing
        "2026-09-17 13:59",
        "2026-09-17 14:00",  # expiry day 14:00 -> CLOSE
        "2026-09-17 14:30",
        "2026-09-18 09:01",  # first bar of the next session -> OPEN
        "2026-09-18 14:00",
    ]

    actions = [(bar, rollover.update(_ns(bar)), rollover.frozen) for bar in bars]

    assert actions == [
        ("2026-09-16 14:00", None, False),
        ("2026-09-17 13:59", None, False),
        ("2026-09-17 14:00", RollAction.CLOSE, True),
        ("2026-09-17 14:30", None, True),
        ("2026-09-18 09:01", RollAction.OPEN, False),
        ("2026-09-18 14:00", None, False),
    ]


def test_node_started_after_14_on_expiry_day_closes_on_its_first_bar() -> None:
    rollover = FuturesRollover()

    assert rollover.update(_ns("2026-09-17 14:20")) is RollAction.CLOSE
