from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import requests


class EntradeEnvironment(StrEnum):
    """External boundary environment exposed by Entrade."""

    DEMO = "demo"
    LIVE = "live"


@dataclass(frozen=True)
class EntradeClientConfig:
    """External boundary configuration for Entrade HTTP requests."""

    environment: EntradeEnvironment = EntradeEnvironment.DEMO
    base_url: str = "https://services.entrade.com.vn"
    timeout_seconds: float = 30.0


class EntradeApiError(RuntimeError):
    """External boundary error returned by Entrade."""

    def __init__(
        self,
        message: str,
        *,
        method: str,
        url: str,
        status_code: int | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.method = method
        self.url = url
        self.status_code = status_code
        self.payload = payload


class EntradeTransport:
    """External boundary HTTP transport for Entrade."""

    def __init__(
        self,
        config: EntradeClientConfig | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config or EntradeClientConfig()
        self._session = session or requests.Session()
        self._token: str | None = None

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def api_prefix(self) -> str:
        if self.config.environment == EntradeEnvironment.DEMO:
            return "papertrade-entrade-api"
        return "entrade-api"

    def set_token(self, token: str) -> None:
        self._token = token

    def close(self) -> None:
        self._session.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        **kwargs: Any,
    ) -> Any:
        url = self.url_for(path)
        headers = dict(kwargs.pop("headers", {}))
        if authenticated:
            if self._token is None:
                raise EntradeApiError(
                    "Entrade authentication is required",
                    method=method,
                    url=url,
                )
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            response = self._session.request(
                method,
                url,
                headers=headers,
                timeout=self.config.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise EntradeApiError(
                f"Entrade request failed: {exc}",
                method=method,
                url=url,
            ) from exc

        payload = self._response_payload(response)
        if not 200 <= response.status_code < 300:
            raise EntradeApiError(
                f"Entrade returned HTTP {response.status_code}",
                method=method,
                url=url,
                status_code=response.status_code,
                payload=payload,
            )
        return payload

    def _response_payload(self, response: requests.Response) -> Any:
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            request_method = (
                response.request.method or "UNKNOWN" if response.request is not None else "UNKNOWN"
            )
            raise EntradeApiError(
                "Entrade returned a non-JSON response",
                method=request_method,
                url=response.url,
                status_code=response.status_code,
                payload=response.text,
            ) from exc

    def url_for(self, path: str) -> str:
        """Resolve an Entrade resource path without making a request."""
        return f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
