from __future__ import annotations

import ssl
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import urllib3
from dnse import DNSEClient


DNSE_API_VERSION = "2026-07-23"


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
    return DNSERateLimit(limit=int(limit), remaining=int(remaining), reset_at=reset)


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


def create_dnse_rest_client(
    *,
    api_key: str,
    api_secret: str,
    base_url: str = "https://openapi.dnse.com.vn",
    api_version: str = DNSE_API_VERSION,
    rate_limit_observer: RateLimitObserver | None = None,
) -> DNSEClient:
    """Create the official DNSE client with TLS certificate verification enabled."""
    client = DNSEClient(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
        api_version=api_version,
    )

    # SDK 2.0.0 disables certificate verification and exposes no public override.
    pool_manager_type = (
        RateLimitObservingPoolManager if rate_limit_observer is not None else urllib3.PoolManager
    )
    pool_manager_kwargs: dict[str, Any] = {
        "num_pools": 10,
        "maxsize": 10,
        "block": False,
        "timeout": urllib3.Timeout(connect=30.0, read=60.0),
        "cert_reqs": ssl.CERT_REQUIRED,
    }
    if rate_limit_observer is not None:
        pool_manager_kwargs["rate_limit_observer"] = rate_limit_observer

    client._http = pool_manager_type(**pool_manager_kwargs)  # noqa: SLF001
    return client
