"""Daily ETL heartbeat: status file writer + missed-run detection (DEC-012).

The 16:00 LaunchAgent run writes a status file; a separate watcher
(LaunchAgent at 16:10+) checks it and alerts ``RUN MISSING`` when the
scheduled run never happened. Absence of the expected alert IS the alert:
a pipeline that never starts cannot alert by itself.
"""

from __future__ import annotations

import json
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path

STATUS_FILENAME = "daily-etl-status.json"
RUNNING_STALE_AFTER = timedelta(hours=3)

ROOT = Path(__file__).resolve().parents[2]


def status_path(root: Path | None = None) -> Path:
    """Location of the heartbeat status file (repo-root-relative, DEC-012)."""
    base = root if root is not None else ROOT
    return base / "data" / "state" / STATUS_FILENAME


def write_status(
    day: object,
    *,
    result: str,
    root: Path | None = None,
) -> Path:
    """Record one ETL run outcome: result in {"running", "ok", "failed: ..."}."""
    path = status_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "day": str(day),
        "result": result,
        "written_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def check_status(
    *,
    day: object,
    root: Path | None = None,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Classify the heartbeat for ``day``.

    Returns (status, detail) with status in:
      "ok"      - a successful run for this day is on record
      "failed"  - a run happened for this day but failed (already alerted by
                  the run itself; the watcher must stay quiet)
      "missing" - no record for this day, or the record is stale while the
                  run was still marked "running" (hard kill)
    """
    path = status_path(root)
    if not path.exists():
        return "missing", "no status file"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return "missing", f"unreadable status file: {error}"
    if str(payload.get("day")) != str(day):
        return "missing", f"status day {payload.get('day')!r} != {day!r}"
    result = str(payload.get("result", ""))
    if result == "ok":
        return "ok", "ok"
    if result == "running":
        written_at = payload.get("written_at")
        try:
            stamp = datetime.fromisoformat(str(written_at))
        except (TypeError, ValueError):
            return "missing", "running status without timestamp"
        if (now or datetime.now(UTC)) - stamp > RUNNING_STALE_AFTER:
            return "missing", f"stale 'running' since {stamp.isoformat()}"
        return "running", "still running"
    return "failed", result
