from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import urllib3


@dataclass(frozen=True)
class DNSERateLimit:
    """DNSE REST quota metadata reported for one endpoint response."""

    limit: int
    remaining: int
    reset_at: str


RateLimitObserver = Callable[[DNSERateLimit], None]


def parse_dnse_rate_limit_headers(headers: Mapping[str, str]) -> DNSERateLimit | None:
    """Parse DNSE quota headers when the response supplies the complete set."""
    normalized = {name.lower(): value for name, value in headers.items()}
    limit = normalized.get("x-ratelimit-limit")
    remaining = normalized.get("x-ratelimit-remaining")
    reset = normalized.get("x-ratelimit-reset")
    if limit is None or remaining is None or reset is None:
        return None

    return DNSERateLimit(
        limit=int(limit),
        remaining=int(remaining),
        reset_at=reset,
    )


class RateLimitObservingPoolManager(urllib3.PoolManager):
    """Forward DNSE quota metadata while preserving the original response."""

    def __init__(self, *, rate_limit_observer: RateLimitObserver, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._rate_limit_observer = rate_limit_observer

    def request(self, *args: Any, **kwargs: Any) -> urllib3.BaseHTTPResponse:
        response = super().request(*args, **kwargs)
        rate_limit = parse_dnse_rate_limit_headers(response.headers)
        if rate_limit is not None:
            self._rate_limit_observer(rate_limit)
        return response
