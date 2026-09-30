from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import requests

TOKEN_REJECTED_STATUS_CODES = frozenset({401, 403})
LIST_PAGE_SIZE = 100
LIST_MAX_PAGES = 200


class EntradeAccount(StrEnum):
    """
    Account kind exposed by Entrade: demo (papertrade) or live (real money).

    Distinct from the Nautilus node `Environment` context (Backtest, Sandbox,
    Live), which selects the runtime mode rather than the trading account.
    """

    DEMO = "demo"
    LIVE = "live"


@dataclass(frozen=True)
class EntradeClientConfig:
    account: EntradeAccount = EntradeAccount.DEMO
    base_url: str = "https://services.entrade.com.vn"
    timeout_seconds: float = 30.0


class EntradeApiError(RuntimeError):
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
        if self.config.account == EntradeAccount.DEMO:
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


def investor_id_from_token(token: str) -> int | str | None:
    try:
        encoded = token.split(".")[1]
        padding = "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(encoded + padding))
    except (IndexError, ValueError):
        return None
    return claims.get("investorId") or claims.get("investorIdStr")


class EntradeClient(EntradeTransport):
    def __init__(
        self,
        config: EntradeClientConfig | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(config, session=session)
        self._authentication: dict[str, Any] | None = None
        self._credentials: tuple[str, str] | None = None

    @property
    def authentication(self) -> dict[str, Any] | None:
        return self._authentication

    def authenticate(self, username: str, password: str) -> str:
        response = self._request(
            "POST",
            "/entrade-api/v2/auth",
            json={"username": username, "password": password},
            authenticated=False,
        )
        token = response.get("token") if isinstance(response, dict) else None
        if not token:
            raise EntradeApiError(
                "Entrade authentication response did not contain a token",
                method="POST",
                url=self.url_for("/entrade-api/v2/auth"),
                payload=response,
            )
        self._authentication = response
        self._credentials = (username, password)
        authenticated_token = str(token)
        self.set_token(authenticated_token)
        return authenticated_token

    def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        **kwargs: Any,
    ) -> Any:
        try:
            return super()._request(method, path, authenticated=authenticated, **kwargs)
        except EntradeApiError as e:
            # Sign in again and repeat the request once on 401/403. Entrade answers an
            # invalid token with HTTP 401 and does not process the request (verified on the
            # Entrade demo API, 2026-09-30: POST derivative/orders with an invalid token
            # -> 401, no order created; token lifetime 8 h from the JWT iat/exp claims).
            if (
                not authenticated
                or e.status_code not in TOKEN_REJECTED_STATUS_CODES
                or self._credentials is None
            ):
                raise
        self.authenticate(*self._credentials)
        return super()._request(method, path, authenticated=authenticated, **kwargs)

    def get_master_account(self, investor_id: int | str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/{self.api_prefix}/investors/{investor_id}/investor_account",
        )

    def get_account_balance(self, investor_id: int | str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/{self.api_prefix}/account_balances/{investor_id}",
        )

    def list_margin_portfolios(self, investor_id: int | str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/{self.api_prefix}/investors/{investor_id}/derivative_margin_portfolios",
        )

    def get_buying_power(
        self,
        *,
        investor_id: int | str,
        margin_portfolio_id: int,
        symbol: str,
        side: str,
        price: float,
    ) -> dict[str, Any]:
        margin_portfolio_parameter = (
            "bankMarginPortfolioId"
            if self.config.account == EntradeAccount.DEMO
            else "bankMarginPortfolio"
        )
        return self._request(
            "GET",
            f"/{self.api_prefix}/derivative/investors/{investor_id}/ppse",
            params={
                margin_portfolio_parameter: margin_portfolio_id,
                "price": price,
                "symbol": symbol,
                "side": side,
            },
        )

    def list_derivatives(self) -> dict[str, Any]:
        return self._request("GET", f"/{self.api_prefix}/derivatives")

    def place_order(
        self,
        *,
        investor_id: int | str,
        margin_portfolio_id: int,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        price: float,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{self.api_prefix}/derivative/orders",
            json={
                "bankMarginPortfolioId": margin_portfolio_id,
                "investorId": investor_id,
                "symbol": symbol,
                "price": price,
                "orderType": order_type,
                "side": side,
                "quantity": quantity,
            },
        )

    def list_orders(
        self,
        *,
        investor_account_id: int | str,
        start: int = 0,
        end: int = 100,
        sort: str | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "investorAccountId": investor_account_id,
            "_start": start,
            "_end": end,
        }
        if sort is not None:
            params["_sort"] = sort
        if order is not None:
            params["_order"] = order
        return self._request(
            "GET",
            f"/{self.api_prefix}/derivative/orders",
            params=params,
        )

    def list_all_orders(self, *, investor_account_id: int | str) -> list[dict[str, Any]]:
        """Return every order of the account, reading page by page instead of one capped page."""
        return _collect_pages(self.list_orders, investor_account_id=investor_account_id)

    def get_order(self, order_id: int | str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/{self.api_prefix}/derivative/orders/{order_id}",
        )

    def cancel_order(self, order_id: int | str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/{self.api_prefix}/derivative/orders/{order_id}",
        )

    def cancel_all_orders(self, *, investor_account_id: int | str) -> list[dict[str, Any]]:
        orders = self.list_all_orders(investor_account_id=investor_account_id)
        terminal_states = {"Canceled", "Filled", "Rejected", "Expired", "DoneForDay"}
        return [
            self.cancel_order(order["id"])
            for order in orders
            if order.get("orderStatus") not in terminal_states
        ]

    def get_risk_config(
        self,
        *,
        investor_account_id: int | str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/{self.api_prefix}/risk_configs",
            params={"investorAccountId": investor_account_id},
        )

    def update_risk_config(
        self,
        *,
        investor_id: int | str,
        investor_account_id: int | str,
        cut_loss_rate: float,
        trailing_enabled: bool,
        auto_increase_deal_rate: bool,
        enable_auto_deal_deposit_notification: bool,
    ) -> dict[str, Any]:
        cut_loss_field = (
            "defaultCutLossRate"
            if self.config.account == EntradeAccount.DEMO
            else "cutLossRate"
        )
        return self._request(
            "PATCH",
            f"/{self.api_prefix}/risk_configs/{investor_account_id}",
            json={
                cut_loss_field: cut_loss_rate,
                "investorAccountId": investor_account_id,
                "trailingEnabled": trailing_enabled,
                "investorId": investor_id,
                "autoIncreaseDealRate": auto_increase_deal_rate,
                "enableAutoDealDepositNoti": enable_auto_deal_deposit_notification,
            },
        )

    def list_deals(
        self,
        *,
        investor_account_id: int | str,
        start: int = 0,
        end: int = 100,
        sort: str | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "investorAccountId": investor_account_id,
            "_start": start,
            "_end": end,
        }
        if sort is not None:
            params["_sort"] = sort
        if order is not None:
            params["_order"] = order
        return self._request(
            "GET",
            f"/{self.api_prefix}/derivative/deals",
            params=params,
        )

    def list_all_deals(self, *, investor_account_id: int | str) -> list[dict[str, Any]]:
        """Return every deal of the account, reading page by page instead of one capped page."""
        return _collect_pages(self.list_deals, investor_account_id=investor_account_id)

    def close_deal(
        self,
        deal_id: int | str,
        *,
        order_type: str = "LO",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{self.api_prefix}/derivative/deals/{deal_id}/_close_deal",
            json={"orderType": order_type, "triggeredBy": "close-deal"},
        )

    def close_all_deals(self, *, investor_account_id: int | str) -> list[dict[str, Any]]:
        deals = self.list_all_deals(investor_account_id=investor_account_id)
        return [self.close_deal(deal["id"]) for deal in deals if deal.get("status") == "ACTIVE"]


def _collect_pages(fetch: Any, **params: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    for page in range(LIST_MAX_PAGES):
        start = page * LIST_PAGE_SIZE
        payload = fetch(start=start, end=start + LIST_PAGE_SIZE, **params)
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        new_rows = [row for row in rows if row.get("id") not in seen_ids]
        # Stop when a page adds no new IDs, e.g. if the server ignores _start.
        if not new_rows:
            return records
        seen_ids.update(row.get("id") for row in new_rows)
        records.extend(new_rows)
        if len(rows) < LIST_PAGE_SIZE:
            return records
    raise EntradeApiError(
        f"Entrade list exceeded {LIST_MAX_PAGES * LIST_PAGE_SIZE} records; refusing a partial result",
        method="GET",
        url=getattr(fetch, "__name__", "list"),
    )


def resolve_entrade_account_ids(
    username: str,
    password: str,
    *,
    account: EntradeAccount,
    client_name: str,
    investor_id: int | str | None = None,
) -> tuple[str, str]:
    """Sign in and return (investor ID, Nautilus account ID ``<client_name>-<investorAccountId>``).

    A Nautilus execution client needs its account ID when it is constructed, before it
    connects, so a node builder calls this first.
    """
    client = EntradeClient(EntradeClientConfig(account=account))
    try:
        token = client.authenticate(username, password)
        investor_id = investor_id or investor_id_from_token(token)
        if investor_id is None:
            raise EntradeApiError(
                "Entrade investor ID was not given and the token does not contain it",
                method="POST",
                url=client.url_for("/entrade-api/v2/auth"),
            )
        balance = client.get_account_balance(investor_id)
    finally:
        client.close()
    return str(investor_id), f"{client_name}-{balance['investorAccountId']}"
