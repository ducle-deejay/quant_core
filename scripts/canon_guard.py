#!/usr/bin/env python3
"""Canon guard: PreToolUse hook protecting the frozen design layer.

Receives the harness hook payload as JSON on stdin (Claude Code, Codex and
the official DSH bridges all speak this shape for command hooks). Extracts
the target file path from Edit/Write tool input and blocks the call with
exit code 2 when the path falls under a protected glob from
ledger.config.json.

Bash-based writes are out of scope here by design; the git pre-commit hook
is the backstop that catches any write path, executed by any agent.
"""

from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_protected_globs() -> list[str]:
    config_path = ROOT / "ledger.config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        globs = config.get("protected_globs", [])
        return [g for g in globs if isinstance(g, str)]
    except (OSError, json.JSONDecodeError):
        # Fail CLOSED: an unreadable kit config must not silently open the
        # canon. Blocking every edit is loud and immediately diagnosable.
        print("canon-guard: ledger.config.json unreadable - blocking edit", file=sys.stderr)
        raise SystemExit(2)


def is_protected(path: str, globs: list[str]) -> bool:
    normalized = str(Path(path).as_posix())
    return any(fnmatch.fnmatch(normalized, g) or fnmatch.fnmatch(normalized, f"**/{g}")
               for g in globs)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # not our event shape; stay silent

    # Temporary diagnostics: record every invocation so we can see the
    # harness's real tool names and paths. Remove once matcher semantics
    # are confirmed on all target harnesses.
    try:
        with open("/tmp/canon_guard.log", "a", encoding="utf-8") as log:
            log.write(json.dumps({
                "tool": payload.get("tool_name"),
                "path": (payload.get("tool_input") or {}).get("file_path"),
            }) + "\n")
    except OSError:
        pass

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not file_path:
        return 0  # no file target (e.g. Bash) - pre-commit covers it

    globs = load_protected_globs()
    if is_protected(file_path, globs):
        config = json.loads((ROOT / "ledger.config.json").read_text(encoding="utf-8"))
        print(
            f"BLOCKED: {file_path} is inside the frozen design canon "
            f"({config['canon_dir']}/).\n"
            "The canon states intent and never changes.\n"
            "Record the disagreement in the living ledger instead: see "
            f"{config['ledger_dir']}/HOME.md and skill 'ledger-discipline'.\n"
            "If behaviour truly evolved past design, write a reconciliation "
            "note; if design itself must change, that is a governance decision "
            "for the owner, never an agent edit.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
