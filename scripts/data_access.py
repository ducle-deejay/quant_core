#!/usr/bin/env python3
from __future__ import annotations

import argparse
import grp
import os
import pwd
import stat
import subprocess
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DATA_ROOT = Path(os.environ["DATA_ROOT"])
PUBLISHED_OS_SHARE = "published_os"

EVERY_USER_GROUP = "staff"
CLOSED_GROUP = "admin"
OS_GROUP = "os_access"
EXECUTION_GROUP = "execution_access"
OWNER_ONLY = ("catalog", "catalog_snapshots", "raw", "logs", "validation")
DATA_TYPE_GROUPS = {
    "bars": EVERY_USER_GROUP,
    "instruments": EVERY_USER_GROUP,
    "trades": EXECUTION_GROUP,
    "order_book_depths": EXECUTION_GROUP,
}


def layout() -> dict[Path, tuple[str, int]]:
    expected = {DATA_ROOT / name: (EVERY_USER_GROUP, 0o700) for name in OWNER_ONLY}
    expected[DATA_ROOT / "published"] = (EVERY_USER_GROUP, 0o755)
    expected[DATA_ROOT / "published_os"] = (OS_GROUP, 0o750)
    for catalog in (DATA_ROOT / "catalog", DATA_ROOT / "published" / "catalog", DATA_ROOT / "published_os" / "catalog"):
        if not catalog.exists():
            continue
        expected[catalog / "data"] = (CLOSED_GROUP, 0o755)
        for data_type in (path for path in (catalog / "data").iterdir() if path.is_dir()):
            group = DATA_TYPE_GROUPS.get(data_type.name, CLOSED_GROUP)
            expected[data_type] = (group, 0o755 if group == EVERY_USER_GROUP else 0o750)
    return expected


def setup() -> None:
    owner = pwd.getpwuid(DATA_ROOT.stat().st_uid)
    missing = [group for group in (OS_GROUP, EXECUTION_GROUP) if not _group_exists(group)]
    if missing:
        raise SystemExit(f"create these groups first: {', '.join(missing)}")
    (DATA_ROOT / "published_os").mkdir(exist_ok=True)
    for path, (group, mode) in layout().items():
        os.chown(path, owner.pw_uid, grp.getgrnam(group).gr_gid)
        path.chmod(mode)
    shares = subprocess.run(["sharing", "-l"], check=True, capture_output=True, text=True).stdout
    if f"name:\t\t{PUBLISHED_OS_SHARE}\n" not in shares:
        subprocess.run(
            ["sharing", "-a", str(DATA_ROOT / "published_os"), "-n", PUBLISHED_OS_SHARE, "-S", PUBLISHED_OS_SHARE,
             "-s", "001", "-g", "000", "-R", "1"],
            check=True,
        )
    status()


def status() -> None:
    drifted = [
        f"{path}: {_group_and_mode(path)} instead of {group} {mode:o}"
        for path, (group, mode) in layout().items()
        if _group_and_mode(path) != f"{group} {mode:o}"
    ]
    owner = pwd.getpwuid(DATA_ROOT.stat().st_uid).pw_name
    rows = [("user", "bars", "trades", "order book")]
    for user in _users():
        os_access = user == owner or _is_member(user, OS_GROUP)
        execution = "yes" if user == owner or _is_member(user, EXECUTION_GROUP) else "no"
        rows.append((user, "all" if os_access else "before OS", execution, execution))
    width = max(len(row[0]) for row in rows) + 2
    for user, bars, trades, book in rows:
        print(f"{user:<{width}}{bars:<12}{trades:<8}{book}")
    outside = [group for group in (OS_GROUP, EXECUTION_GROUP) if not _is_member(owner, group)]
    if outside:
        print(f"\nAdd {owner} to {', '.join(outside)}: publishing keeps a directory's group only for its members.")
    if drifted:
        print(f"\n{len(drifted)} directories differ from setup, so the access above does not hold yet.")
        print("Run: sudo .venv/bin/python scripts/data_access.py setup\n  " + "\n  ".join(drifted))


def _users() -> list[str]:
    listing = subprocess.run(["dscl", ".", "-list", "/Users", "UniqueID"], check=True, capture_output=True, text=True).stdout
    return [name for name, uid in (line.split() for line in listing.splitlines()) if int(uid) > 500 and not name.startswith("_")]


def _is_member(user: str, group: str) -> bool:
    return _group_exists(group) and subprocess.run(
        ["dseditgroup", "-o", "checkmember", "-m", user, group], capture_output=True,
    ).returncode == 0


def _group_exists(group: str) -> bool:
    try:
        grp.getgrnam(group)
    except KeyError:
        return False
    return True


def _group_and_mode(path: Path) -> str:
    if not path.exists():
        return "missing"
    info = path.stat()
    return f"{grp.getgrgid(info.st_gid).gr_name} {stat.S_IMODE(info.st_mode):o}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("setup", "status"))
    {"setup": setup, "status": status}[parser.parse_args().command]()


if __name__ == "__main__":
    main()
