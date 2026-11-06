"""Daily log files per job, and the stage logging every ETL source uses."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any

from market_data import LOCAL_TIMEZONE
from market_data.sources import ETLStageError


TRACEBACK_INDENT = "    "


class _Formatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, LOCAL_TIMEZONE).isoformat(timespec="seconds")

    def formatException(self, ei: Any) -> str:
        # Indented so the traceback reads as part of the ERROR line above it
        return "\n".join(TRACEBACK_INDENT + line for line in super().formatException(ei).splitlines())


def configure(log_dir: Path, job: str, run_day: date) -> Path:
    """Route every logger to the job's log file for run_day and return that file's path."""
    path = log_dir / job / f"{run_day.isoformat()}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = _Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.FileHandler(path, encoding="utf-8")]
    if sys.stderr.isatty():
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    return path


def fields(**values: object) -> str:
    """key=value text; whitespace inside a value collapses so one log event stays on one line."""
    return " ".join(f"{key}={' '.join(str(value).split())}" for key, value in values.items())


@contextmanager
def stage(source: str, name: str, day: date) -> Generator[dict[str, object]]:
    """Log a stage's start and its end with duration and the yielded details; a failure is logged with its traceback and raised as ETLStageError."""
    logger = logging.getLogger(f"{source}.{name}")
    logger.info("started %s", fields(day=day))
    details: dict[str, object] = {}
    started = time.monotonic()
    try:
        yield details
    except ETLStageError:
        raise
    except Exception as error:
        logger.exception(
            "failed %s",
            fields(day=day, duration_min=_minutes(started), error=f"{type(error).__name__}: {error}"),
        )
        raise ETLStageError(source=source, stage=name, cause=error) from error
    logger.info("done %s", fields(day=day, duration_min=_minutes(started), **details))


def _minutes(started: float) -> str:
    return f"{(time.monotonic() - started) / 60:.1f}"
