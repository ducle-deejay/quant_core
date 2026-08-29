"""Daily fallback semantics tests (governing note DEC-009).

The critical regression: a run where Mirae RESOLVED every DNSE-missing
timestamp must SUCCEED - the replaced nox implementation failed the whole
run in that case.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from market_data.daily import DailyDataPipelineError  # noqa: E402
from market_data.daily import _remaining_missing  # noqa: E402
from market_data.daily import run_daily  # noqa: E402


DAY = date(2026, 8, 30)
FULL_DNSE = {"records": {"Bar": 240}, "missing_bar_timestamps": []}
DNSE_WITH_GAPS = {"records": {"Bar": 230}, "missing_bar_timestamps": [100, 101, 102]}
MIRAE_ADDED_ALL = {"records": {"Bar": 3, "SkippedBar": 0, "added_bar_timestamps": [100, 101, 102]}}
MIRAE_ADDED_PARTIAL = {"records": {"Bar": 1, "SkippedBar": 0, "added_bar_timestamps": [100]}}
MIRAE_ADDED_NONE = {"records": {"Bar": 0, "SkippedBar": 3, "added_bar_timestamps": []}}


def test_dnse_ok_mirae_ok():
    report = run_daily(
        day=DAY,
        run_dnse=lambda d: dict(FULL_DNSE),
        run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
    )
    assert report["day"] == DAY.isoformat()
    assert report["dnse"]["records"]["Bar"] == 240


def test_mirae_resolves_dnse_gaps_succeeds():
    # THE regression: nox failed here; we must succeed.
    report = run_daily(
        day=DAY,
        run_dnse=lambda d: dict(DNSE_WITH_GAPS),
        run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
    )
    assert report["mirae"]["records"]["Bar"] == 3


def test_remaining_gaps_after_both_sources_fails():
    try:
        run_daily(
            day=DAY,
            run_dnse=lambda d: dict(DNSE_WITH_GAPS),
            run_mirae=lambda d: dict(MIRAE_ADDED_PARTIAL),
        )
    except DailyDataPipelineError as error:
        assert "remain missing" in str(error)
    else:
        raise AssertionError("expected DailyDataPipelineError")


def test_dnse_failed_raises_even_if_mirae_ok():
    try:
        run_daily(
            day=DAY,
            run_dnse=lambda d: (_ for _ in ()).throw(RuntimeError("dnse down")),
            run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
        )
    except DailyDataPipelineError as error:
        assert "DNSE" in str(error)
    else:
        raise AssertionError("expected DailyDataPipelineError")


def test_mirae_failure_covered_by_dnse_is_warning_not_failure():
    report = run_daily(
        day=DAY,
        run_dnse=lambda d: dict(FULL_DNSE),
        run_mirae=lambda d: (_ for _ in ()).throw(RuntimeError("mirae down")),
    )
    assert report["mirae_error"] == "mirae down"
    assert report["dnse"]["records"]["Bar"] == 240


def test_remaining_missing_math():
    assert _remaining_missing(dict(FULL_DNSE), None) == []
    assert _remaining_missing(dict(DNSE_WITH_GAPS), dict(MIRAE_ADDED_ALL)) == []
    assert _remaining_missing(dict(DNSE_WITH_GAPS), dict(MIRAE_ADDED_PARTIAL)) == [101, 102]
    assert _remaining_missing(dict(DNSE_WITH_GAPS), dict(MIRAE_ADDED_NONE)) == [100, 101, 102]
    assert _remaining_missing(None, None) == []


def _run_all() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as error:
                failures += 1
                print(f"FAIL {name}: {error}")
            except Exception as error:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {type(error).__name__}: {error}")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _run_all() else 0)
