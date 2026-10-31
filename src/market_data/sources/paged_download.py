"""Parallel download of time-filtered, token-paginated data; every window keeps only records in [start, end)."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


PAGE_FILE_FORMAT = "page_{:05d}.json"
MAX_RATE_LIMIT_RETRIES = 6

# (window start, window end, page token) -> (raw page, parsed page, next token or None after the window's last page)
PageFetcher = Callable[[int, int, str | None], tuple[str, Any, str | None]]
# (parsed page, window start, window end) -> page text without records outside [start, end), or None when all are inside
PageTrimmer = Callable[[Any, int, int], str | None]


class RateLimited(Exception):
    """Raised by a fetcher when the provider throttles; the page is retried after a backoff."""


def split_range(start: int, end: int, boundaries: Sequence[int]) -> list[tuple[int, int]]:
    """Half-open windows covering [start, end), split at the boundaries inside it."""
    points = [start, *sorted(value for value in boundaries if start < value < end), end]
    return list(zip(points[:-1], points[1:]))


def download_windows(
    *,
    make_fetcher: Callable[[], PageFetcher],
    trim_page: PageTrimmer,
    windows: Sequence[tuple[int, int]],
    destination: Path,
    max_workers: int,
) -> int:
    """Download windows in parallel, one fetcher each; pages are numbered by window order, then page order."""
    staging = destination / ".windows"
    staging.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="paged-download") as executor:
        futures = [
            executor.submit(_download_window, make_fetcher(), trim_page, start, end, staging / f"{index:04d}")
            for index, (start, end) in enumerate(windows)
        ]
        counts = [future.result() for future in futures]

    number = 0
    for index, count in enumerate(counts):
        for page in range(1, count + 1):
            number += 1
            os.replace(staging / f"{index:04d}" / PAGE_FILE_FORMAT.format(page), destination / PAGE_FILE_FORMAT.format(number))
    shutil.rmtree(staging)
    return number


def _download_window(
    fetch_page: PageFetcher,
    trim_page: PageTrimmer,
    start: int,
    end: int,
    directory: Path,
) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    token: str | None = None
    seen_tokens: set[str] = set()
    page = 0
    while True:
        raw, parsed, token = _fetch_with_backoff(fetch_page, start, end, token)
        page += 1
        trimmed = trim_page(parsed, start, end)
        (directory / PAGE_FILE_FORMAT.format(page)).write_text(raw if trimmed is None else trimmed, encoding="utf-8")
        if not token:
            return page
        if token in seen_tokens:
            raise ValueError(f"Repeated page token in window [{start}, {end})")
        seen_tokens.add(token)


def _fetch_with_backoff(fetch_page: PageFetcher, start: int, end: int, token: str | None) -> tuple[str, Any, str | None]:
    for attempt in range(MAX_RATE_LIMIT_RETRIES - 1):
        try:
            return fetch_page(start, end, token)
        except RateLimited:
            time.sleep(min(60.0, 2.0 ** (attempt + 1)))
    return fetch_page(start, end, token)
