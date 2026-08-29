"""Schedule the daily DNSE + Mirae ETL as a macOS LaunchAgent.

Usage: .venv/bin/python3 apps/data/daily/schedule.py [--launch-agent PATH]

Installs (or refreshes) a LaunchAgent that runs the daily pipeline at the
configured weekday time in Asia/Ho_Chi_Minh. Mirror of the nox pattern the
previous data pipeline used; keep the same label per machine.
"""

from __future__ import annotations

import argparse
import plistlib
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONFIG = HERE / "config" / "pipeline.json"
LABEL = "io.quant-core.daily-data-etl"
RUN_HOUR = 17  # after the VN close (14:45) so the day's bars are complete
RUN_MINUTE = 30


def main() -> None:
    parser = argparse.ArgumentParser(description="Schedule the daily DNSE + Mirae ETL")
    parser.add_argument(
        "--launch-agent",
        type=Path,
        default=Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist",
    )
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    if args.uninstall:
        _unload(args.launch_agent)
        args.launch_agent.unlink(missing_ok=True)
        print(f"removed {args.launch_agent}")
        return

    payload = _launch_agent(
        python_executable=Path(sys.executable),
        pipeline_path=(HERE / "pipeline.py").resolve(),
        config_path=args.config.resolve(),
    )
    args.launch_agent.parent.mkdir(parents=True, exist_ok=True)
    args.launch_agent.write_bytes(plistlib.dumps(payload))
    _unload(args.launch_agent)
    _load(args.launch_agent)
    print(f"installed {args.launch_agent}")


def _launch_agent(
    *,
    python_executable: Path,
    pipeline_path: Path,
    config_path: Path,
) -> dict[str, object]:
    now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(python_executable),
            str(pipeline_path),
            "--config",
            str(config_path),
        ],
        "StartCalendarInterval": {
            "Hour": RUN_HOUR,
            "Minute": RUN_MINUTE,
            "Weekday": [1, 2, 3, 4, 5],  # Mon-Fri (launchd 1=Sunday..7=Saturday)
        },
        "WorkingDirectory": str(ROOT),
        "StandardOutPath": str(ROOT / "data" / "logs" / "daily-etl.out.log"),
        "StandardErrorPath": str(ROOT / "data" / "logs" / "daily-etl.err.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
            "PYTHONUNBUFFERED": "1",
        },
        "ProcessType": "Background",
    }


def _unload(path: Path) -> None:
    if not path.exists():
        return
    subprocess.run(
        ["launchctl", "unload", str(path)],
        check=False,
        capture_output=True,
    )


def _load(path: Path) -> None:
    subprocess.run(
        ["launchctl", "load", str(path)],
        check=False,
        capture_output=True,
    )


if __name__ == "__main__":
    main()
