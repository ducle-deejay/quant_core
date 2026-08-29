from __future__ import annotations

import base64
import json
from typing import Any

import requests

from trading.adapters.entrade.transport import EntradeApiError
from trading.adapters.entrade.transport import EntradeClientConfig
from trading.adapters.entrade.transport import EntradeEnvironment
from trading.adapters.entrade.transport import EntradeTransport


def investor_id_from_token(token: str) -> int | str | None:
    try:
        encoded = token.split(".")[1]
        padding = "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(encoded + padding))
    except (IndexError, ValueError):
        return None
    return claims.get("investorId") or claims.get("investorIdStr")


class EntradeClient(EntradeTransport):
    """External boundary client exposing current Entrade resources."""

    def __init__(
        self,
        config: EntradeClientConfig | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(config, session=session)
        self._authentication: dict[str, Any] | None = None

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
        authenticated_token = str(token)
        self.set_token(authenticated_token)
        return authenticated_token

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
        return self._request(
            "GET",
            f"/{self.api_prefix}/derivative/investors/{investor_id}/ppse",
            params={
                "bankMarginPortfolio": margin_portfolio_id,
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
        orders = self.list_orders(investor_account_id=investor_account_id).get("data", [])
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
            if self.config.environment == EntradeEnvironment.DEMO
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
        deals = self.list_deals(investor_account_id=investor_account_id, end=255).get("data", [])
        return [self.close_deal(deal["id"]) for deal in deals if deal.get("status") == "ACTIVE"]
