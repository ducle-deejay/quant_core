# spec: 40-tests.md E24 — runner CLI surface

import subprocess
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parents[2] / "apps" / "trading" / "run.py"


def test_run_help_lists_flags():
    proc = subprocess.run(
        [sys.executable, str(RUN), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(RUN.parents[2]),
    )
    assert proc.returncode == 0
    assert "--config" in proc.stdout
    assert "--confirm-live-account" in proc.stdout
