#!/usr/bin/env python3
"""Ledger sweep (rule M3): report drift debt and verify design links.

Walks every markdown note under docs/ledger/, parses front matter, then:

1. Counts notes by lifecycle status (open/triaged/resolved/superseded).
   The open count is the visible drift debt of the project.
2. Resolves every `design:` reference (a canon doc_id such as
   STG-1-CANONICAL-SIM) against the front matter of files under
   docs/enhanced/. A reference that resolves nowhere is a broken link.
3. Verifies each note file name starts with its declared doc_id.

Exit code is non-zero when any link is broken or any note violates the
naming rule, so the script can gate commits.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "ledger"
CANON = ROOT / "docs" / "enhanced"

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


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


def collect_canon_ids() -> set[str]:
    ids: set[str] = set()
    for path in CANON.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        fields = parse_front_matter(text)
        if "doc_id" in fields:
            ids.add(fields["doc_id"])
    return ids


def main() -> int:
    if not LEDGER.is_dir():
        print(f"ledger directory missing: {LEDGER}")
        return 1

    canon_ids = collect_canon_ids()
    status_counts: dict[str, int] = {}
    broken_links: list[str] = []
    naming_violations: list[str] = []
    note_count = 0

    # The charter/index file follows the vault convention of being named
    # HOME.md with an approved status; lifecycle rules apply to notes only.
    charter_names = {"HOME.md"}

    for path in sorted(LEDGER.rglob("*.md")):
        if path.name in charter_names:
            continue
        note_count += 1
        fields = parse_front_matter(path.read_text(encoding="utf-8"))
        doc_id = fields.get("doc_id", "(missing)")
        status = fields.get("status", "unknown").strip()
        status_counts[status] = status_counts.get(status, 0) + 1

        if doc_id != "(missing)" and not path.name.startswith(doc_id):
            naming_violations.append(f"{path.name}: doc_id {doc_id}")

        for ref in split_refs(fields.get("design", "")):
            if ref not in canon_ids:
                broken_links.append(f"{path.name}: design ref '{ref}' not in canon")

    print("=== LEDGER SWEEP ===")
    print(f"notes scanned      : {note_count}")
    for status in ("open", "triaged", "resolved", "superseded"):
        padded = status_counts.get(status, 0)
        print(f"{status:<19}: {padded}")
    unknown = sum(v for k, v in status_counts.items() if k not in
                  ("open", "triaged", "resolved", "superseded"))
    if unknown:
        print(f"unknown-status     : {unknown}")

    drift_debt = status_counts.get("open", 0)
    print(f"\ndrift debt (open)  : {drift_debt}")

    failed = False
    for item in broken_links + naming_violations:
        print(f"BROKEN: {item}")
        failed = True

    if failed:
        print("\nSWEEP FAILED")
        return 1
    print("\nSWEEP OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
