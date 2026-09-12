# spec: 40-tests.md D — expiry gate (semantics ported from nox test_runtime_expiry)

import calendar
from datetime import date

import pandas as pd
import pytest

from core.expiry import (
    apply_expiry_gate,
    vn30_front_month_expiry_cutoff_utc,
    vn30_front_month_expiry_date_local,
)

FRESH = lambda: __import__("core.expiry", fromlist=["ExpiryState"]).ExpiryState()


def local_ts(y, m, d, hh=0, mm=0):
    return pd.Timestamp(year=y, month=m, day=d, hour=hh, minute=mm, tz="Asia/Ho_Chi_Minh")


def test_third_thursday_known_month():
    # external truth: September 2026 Thursdays from calendar module
    cal = calendar.monthcalendar(2026, 9)
    thursdays = [w[calendar.THURSDAY] for w in cal if w[calendar.THURSDAY] != 0]
    expected = date(2026, 9, thursdays[2])
    assert vn30_front_month_expiry_date_local(local_ts(2026, 9, 10)) == expected
    assert expected == date(2026, 9, 17)


def test_holiday_fallback_walks_back_to_working_date():
    # 2026-09-17 (third Thursday) removed from working dates -> 2026-09-16
    working = ("2026-09-14", "2026-09-15", "2026-09-16")
    assert vn30_front_month_expiry_date_local(
        local_ts(2026, 9, 10), working_dates=working
    ) == date(2026, 9, 16)


def test_cutoff_is_1400_local_on_expiry_day():
    ts = local_ts(2026, 9, 17, 10, 0)
    cutoff = vn30_front_month_expiry_cutoff_utc(ts)
    assert cutoff.tz_convert("Asia/Ho_Chi_Minh").strftime("%H:%M") == "14:00"
    assert cutoff.tz_convert("Asia/Ho_Chi_Minh").date() == date(2026, 9, 17)


def test_force_flat_at_cutoff_and_idempotent():
    ts = local_ts(2026, 9, 17, 14, 0)
    state = FRESH()
    first = apply_expiry_gate(ts, 5, 2, state, enabled=True)
    assert first.force_flat and first.approved_target_contracts == 0
    assert first.reason == "expiry-force-close"
    second = apply_expiry_gate(ts, 5, 0, first.state, enabled=True)
    assert second.approved_target_contracts == 0
    assert second.reentry_blocked and not second.force_flat


def test_before_cutoff_is_reduce_only():
    ts = local_ts(2026, 9, 17, 13, 59)
    res = apply_expiry_gate(ts, -5, -3, FRESH(), enabled=True)
    assert res.approved_target_contracts == -3  # growing |position| blocked
    assert res.reason == "expiry-reduce-only"
    ok = apply_expiry_gate(ts, -2, -3, FRESH(), enabled=True)
    assert ok.approved_target_contracts == -2  # reducing allowed
    assert ok.reason == "expiry-reduce-only"


def test_reentry_blocked_until_next_day():
    day = local_ts(2026, 9, 17, 14, 30)
    forced = apply_expiry_gate(day, 4, 0, FRESH(), enabled=True)
    later = apply_expiry_gate(local_ts(2026, 9, 17, 15, 0), 4, 0, forced.state, enabled=True)
    assert later.approved_target_contracts == 0 and later.reentry_blocked
    next_day = apply_expiry_gate(local_ts(2026, 9, 18, 9, 0), 4, 0, later.state, enabled=True)
    assert next_day.approved_target_contracts == 4 and not next_day.reentry_blocked


def test_non_expiry_day_passes_through():
    res = apply_expiry_gate(local_ts(2026, 9, 10, 14, 30), 5, 2, FRESH(), enabled=True)
    assert res.approved_target_contracts == 5 and not res.force_flat


def test_disabled_bypasses_everything():
    res = apply_expiry_gate(local_ts(2026, 9, 17, 14, 0), 5, 2, FRESH(), enabled=False)
    assert res.approved_target_contracts == 5 and not res.force_flat
    assert res.state.blocked_session_date is None


@pytest.mark.parametrize("minute", [59, 0])
def test_cutoff_boundary_minute(minute):
    ts = local_ts(2026, 9, 17, 13, minute) if minute == 59 else local_ts(2026, 9, 17, 14, 0)
    res = apply_expiry_gate(ts, 5, 2, FRESH(), enabled=True)
    if minute == 59:
        assert res.reason == "expiry-reduce-only"
    else:
        assert res.force_flat
