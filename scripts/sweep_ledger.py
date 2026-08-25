#!/usr/bin/env python3
"""Ledger sweep (rule M3): report drift debt and verify design links.

Configuration is read from ledger.config.json at the repository root so the
same kit works on any project: canon directory, ledger directory, note-class
prefixes, and lifecycle statuses are all project parameters.

For every markdown note under the ledger directory this script:

1. Counts notes by lifecycle status. The open count is the visible drift
   debt of the project.
2. Resolves every `design:` reference (a canon doc_id) against the front
   matter of files under the canon directory. An unresolved reference is a
   broken link.
3. Verifies each note file name starts with its declared doc_id, and that
   every status used belongs to the configured vocabulary.

Exit code is non-zero when any link is broken or any convention is violated,
so the script can gate commits.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "ledger.config.json"
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        print(f"FATAL: kit config missing: {CONFIG_PATH}")
        raise SystemExit(1)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for key in ("canon_dir", "ledger_dir", "protected_globs", "statuses"):
        if key not in config:
            print(f"FATAL: kit config missing required key '{key}'")
            raise SystemExit(1)
    return config


def parse_front_matter(text: str) -> dict[str, str]:
    """Parse a flat YAML-ish block: key: value with optional [a, b] lists."""
    match = FRONT_MATTER.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def split_refs(value: str) -> list[str]:
    """Split '[a, b]' or 'a, b' into clean reference tokens."""
    value = value.strip().strip("[]")
    if not value:
        return []
    return [part.strip().strip("'\"") for part in value.split(",") if part.strip()]


def collect_canon_ids(canon_dir: Path) -> set[str]:
    ids: set[str] = set()
    for path in canon_dir.rglob("*.md"):
        fields = parse_front_matter(path.read_text(encoding="utf-8"))
        if "doc_id" in fields:
            ids.add(fields["doc_id"])
    return ids


def main() -> int:
    config = load_config()
    ledger_dir = ROOT / config["ledger_dir"]
    canon_dir = ROOT / config["canon_dir"]
    statuses: list[str] = config["statuses"]

    if not ledger_dir.is_dir():
        print(f"FATAL: ledger directory missing: {ledger_dir}")
        return 1
    if not canon_dir.is_dir():
        print(f"FATAL: canon directory missing: {canon_dir}")
        return 1

    charter_names = {"HOME.md"}  # index/charter files follow vault conventions
    canon_ids = collect_canon_ids(canon_dir)

    status_counts: dict[str, int] = {status: 0 for status in statuses}
    broken_links: list[str] = []
    naming_violations: list[str] = []
    unknown_status_notes: list[str] = []
    note_count = 0

    class_prefixes = tuple(config.get("note_classes", {}).keys())

    for path in sorted(ledger_dir.rglob("*.md")):
        if path.name in charter_names:
            continue
        note_count += 1
        fields = parse_front_matter(path.read_text(encoding="utf-8"))
        doc_id = fields.get("doc_id", "(missing)")
        status = fields.get("status", "(missing)")

        if doc_id != "(missing)" and not path.name.startswith(doc_id):
            naming_violations.append(f"{path.name}: doc_id {doc_id}")
        if class_prefixes and not path.name.startswith(class_prefixes):
            naming_violations.append(f"{path.name}: file name outside note classes")

        if status in status_counts:
            status_counts[status] += 1
        else:
            unknown_status_notes.append(f"{path.name}: status '{status}'")

        for ref in split_refs(fields.get("design", "")):
            if ref not in canon_ids:
                broken_links.append(f"{path.name}: design ref '{ref}' not in canon")

    print("=== LEDGER SWEEP ===")
    print(f"notes scanned      : {note_count}")
    for status in statuses:
        print(f"{status:<19}: {status_counts.get(status, 0)}")

    drift_debt = status_counts.get("open", 0)
    print(f"\ndrift debt (open)  : {drift_debt}")

    failed = False
    for item in broken_links + naming_violations + unknown_status_notes:
        print(f"BROKEN: {item}")
        failed = True

    if failed:
        print("\nSWEEP FAILED")
        return 1
    print("\nSWEEP OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
