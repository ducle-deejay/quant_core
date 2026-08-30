"""Unit tests for the risk overlay transition JSONL log (observability only).

Covers the pure helpers in ``trading.risk.overlay`` (``format_transition``,
``append_transition``, ``transitions_since``) that record RiskOverlayActor
state transitions (ACTIVE/HALTED/REDUCING + reason) as JSONL for the
acceptance layer to match against the trigger matrix. The actor itself needs
a Nautilus TradingNode, so only the helpers are tested here - the same split
as ``test_risk.py`` (pure core tested, thin wiring verified by review).

Governing notes (design-derived tests, ledger rule M4):
- canon STG-7-RISK-OVERLAY : layer-3 ladder (soft halt / flatten / shutdown),
  layer-2 exposure caps, dead-man's switch / stale-feed detector; the trigger
  matrix in ``trading.risk.state`` is already covered by ``test_risk.py``
- DEC-008 : risk overlay built to live standard in the paper phase

Run as a plain assert runner:
``.venv/bin/python3 src/trading/tests/test_risk_overlay_log.py``
"""

from __future__ import annotations

import json
import os
import tempfile

from trading.risk.overlay import append_transition
from trading.risk.overlay import format_transition
from trading.risk.overlay import transitions_since
from trading.risk.state import ACTIVE, HALTED, REDUCING, REASON_EXPOSURE, REASON_LOSS


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _read_lines(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# --- formatting ---------------------------------------------------------------

def test_format_transition_shape() -> None:
    line = format_transition(1_700_000_000_123_456_789, ACTIVE, HALTED, REASON_LOSS)
    record = json.loads(line)
    _assert(
        list(record.keys()) == ["ts_ns", "previous", "current", "reason"],
        f"key order={list(record.keys())}",
    )
    _assert(
        record
        == {
            "ts_ns": 1_700_000_000_123_456_789,
            "previous": ACTIVE,
            "current": HALTED,
            "reason": REASON_LOSS,
        },
        f"record={record}",
    )


def test_format_transition_reason_null() -> None:
    record = json.loads(format_transition(1, ACTIVE, ACTIVE, None))
    _assert(record["reason"] is None, "None reason must serialize as JSON null")


# --- appending ---------------------------------------------------------------

def test_append_transition_creates_dirs_and_writes_jsonl() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "nested", "logs", "transitions.jsonl")
        append_transition(path, format_transition(1, ACTIVE, HALTED, REASON_LOSS))
        _assert(os.path.isfile(path), "parent dirs must be created and file written")
        records = _read_lines(path)
        _assert(len(records) == 1, f"one line expected, got {len(records)}")
        _assert(records[0]["current"] == HALTED, "record content")


def test_append_transition_appends_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "transitions.jsonl")
        append_transition(path, format_transition(1, ACTIVE, HALTED, REASON_LOSS))
        append_transition(path, format_transition(2, HALTED, ACTIVE, None))
        records = _read_lines(path)
        _assert(len(records) == 2, f"two lines expected, got {len(records)}")
        _assert(records[1]["previous"] == HALTED, "second record previous")


def test_append_transition_never_raises_on_write_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        blocker = os.path.join(tmp, "not-a-dir")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")  # a regular file as the parent dir -> OSError
        bad_path = os.path.join(blocker, "transitions.jsonl")
        append_transition(bad_path, format_transition(1, ACTIVE, ACTIVE, None))  # must not raise


# --- transition detection -----------------------------------------------------

def test_transitions_since_no_change_returns_none() -> None:
    records = transitions_since(ACTIVE, "", (ACTIVE, ""))
    _assert(records is None, "unchanged (status, reason) must yield nothing")


def test_transitions_since_change_returns_record() -> None:
    records = transitions_since(HALTED, REASON_LOSS, (ACTIVE, ""))
    _assert(
        records == [{"previous": ACTIVE, "current": HALTED, "reason": REASON_LOSS}],
        f"records={records}",
    )


def test_transitions_since_empty_reason_becomes_null() -> None:
    records = transitions_since(ACTIVE, "", (REDUCING, REASON_EXPOSURE))
    _assert(
        records == [{"previous": REDUCING, "current": ACTIVE, "reason": None}],
        f"records={records}",
    )


def test_transitions_since_initial_record() -> None:
    records = transitions_since(ACTIVE, "", None)
    _assert(
        records == [{"previous": "<start>", "current": ACTIVE, "reason": "startup"}],
        f"records={records}",
    )


# --- runner ------------------------------------------------------------------

def _run_all() -> None:
    tests = [
        fn
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"OK: {len(tests)} tests passed")


if __name__ == "__main__":
    _run_all()
