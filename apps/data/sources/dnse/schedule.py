from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DEFAULT_CONFIG = HERE / "config" / "pipeline.json"
LABEL = "io.quant-core.dnse-daily-etl"


def main() -> None:
    parser = argparse.ArgumentParser(description="Schedule the daily DNSE ETL pipeline")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--launch-agent",
        type=Path,
        default=Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist",
    )
    args = parser.parse_args()
    payload = _launch_agent(
        python_executable=Path(sys.executable),
        config_path=args.config.resolve(),
    )
    args.launch_agent.parent.mkdir(parents=True, exist_ok=True)
    args.launch_agent.write_bytes(plistlib.dumps(payload, sort_keys=True))

    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(args.launch_agent)],
        check=False,
        capture_output=True,
    )
    subprocess.run(["launchctl", "bootstrap", domain, str(args.launch_agent)], check=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{LABEL}"], check=True)


def _launch_agent(*, python_executable: Path, config_path: Path) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(python_executable),
            str(HERE / "pipeline.py"),
            "--config",
            str(config_path),
        ],
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {"TZ": "Asia/Ho_Chi_Minh"},
        "StartCalendarInterval": {"Hour": 16, "Minute": 0},
        "RunAtLoad": False,
        "ProcessType": "Background",
        "ThrottleInterval": 60,
    }


if __name__ == "__main__":
    main()
