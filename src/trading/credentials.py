"""Broker/API credential resolution for the live runner."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = ROOT / ".env"


def load_credentials(env_path: Path | None = None) -> None:
    """Load ``.env`` if present; individual variables can also come from the shell.

    Loaded with ``override=True``: an explicit ``.env`` value replaces a
    stale shell value.
    """
    path = env_path if env_path is not None else DEFAULT_ENV_PATH
    if path.exists():
        load_dotenv(path, override=True)


def require_env(env_var: str) -> str:
    """Return the required environment variable, aborting the run when unset.

    Raises
    ------
    SystemExit
        When the variable is missing (same behavior as the paper runner:
        the missing credential is a start-up abort, not a runtime error).
    """
    value = os.getenv(env_var)
    if value is None:
        raise SystemExit(f"Missing {env_var} in environment or {DEFAULT_ENV_PATH}")
    return value


def optional_env(env_var: str) -> str | None:
    """Return the optional environment variable, or ``None`` when unset."""
    return os.getenv(env_var)
