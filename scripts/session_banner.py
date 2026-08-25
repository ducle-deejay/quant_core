#!/usr/bin/env python3
"""SessionStart hook: print the ledger drift-debt line into fresh sessions."""
import json
import pathlib
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parent.parent
try:
    result = subprocess.run(
        ["python3", str(root / "scripts" / "sweep_ledger.py")],
        capture_output=True, text=True, timeout=30,
    )
    debt = next(
        (line for line in result.stdout.splitlines() if line.startswith("drift debt")),
        "drift debt: sweep unavailable",
    )
except Exception as exc:  # noqa: BLE001 - banner must never block a session
    debt = f"drift debt: sweep error ({exc})"

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": f"[ledger] {debt}. Canon docs/enhanced is frozen; "
                             "living layer is docs/ledger (see AGENTS.md).",
    }
}))
sys.exit(0)
