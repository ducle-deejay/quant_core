from __future__ import annotations

import ssl
from typing import Any

import urllib3
from dnse import DNSEClient

from trading.adapters.dnse.config import DNSE_API_VERSION
from trading.adapters.dnse.rate_limits import RateLimitObserver
from trading.adapters.dnse.rate_limits import RateLimitObservingPoolManager


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

    client._http = pool_manager_type(  # noqa: SLF001
        **pool_manager_kwargs,
    )
    return client
