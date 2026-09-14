from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from typing import Any

from .entrade_api import EntradeClient
from .entrade_api import investor_id_from_token
from .entrade_api import EntradeApiError
from .entrade_api import EntradeAccount


AUDITED_ORDER_TYPES = ("LO", "MTL", "MAK", "MOK")
TERMINAL_ORDER_STATUSES = {"Canceled", "Expired", "Filled", "Rejected"}


class EntradeDemoAuditor:
    """External-boundary acceptance checks for Entrade demo endpoints."""

    def __init__(
        self,
        client: EntradeClient,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if client.config.account != EntradeAccount.DEMO:
            raise ValueError("Entrade demo audit requires the demo account")
        self.client = client
        self._sleep = sleep
        self._checks: list[dict[str, Any]] = []

    def run(
        self,
        *,
        username: str,
        password: str,
        investor_id: int | str | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        if not symbol:
            raise ValueError("Entrade endpoint audit requires a derivative symbol")

        self._checks = []
        token = self._check(
            "authenticate",
            "POST",
            "/entrade-api/v2/auth",
            lambda: self.client.authenticate(username, password),
            sanitize=lambda _: {"token_received": True},
        )
        if token is None:
            return self._result(None)
        resolved_investor_id = investor_id or investor_id_from_token(token)
        if resolved_investor_id is None:
            self._skip(
                "resolve_investor_id", "JWT did not contain investorId and no override was provided"
            )
            return self._result(None)

        context = self._query_demo_state(resolved_investor_id, symbol=symbol)
        safe_start = self._check(
            "verify_safe_order_test_start",
            "GET",
            f"/{self.client.api_prefix}/derivative/orders",
            lambda: self._verify_safe_order_test_start(context, symbol=symbol),
            sanitize=lambda _: {"no_open_orders": True, "no_active_deals": True},
        )
        if safe_start is not None:
            self._run_order_cancel(resolved_investor_id, context)
            self._run_order_type_audit(resolved_investor_id, context)
        else:
            self._skip(
                "place_order", "Order tests require no open order or active deal for the symbol"
            )
            self._skip("cancel_order", "No test order was submitted")
            for order_type in AUDITED_ORDER_TYPES:
                self._skip(
                    f"{order_type.lower()}_place_fill_order",
                    "Order tests require no open order or active deal for the symbol",
                )
        self._run_risk_config_update(resolved_investor_id, context)
        return self._result(resolved_investor_id)

    def _query_demo_state(
        self,
        investor_id: int | str,
        *,
        symbol: str | None,
    ) -> dict[str, Any]:
        prefix = self.client.api_prefix
        master = self._check(
            "get_master_account",
            "GET",
            f"/{prefix}/investors/{investor_id}/investor_account",
            lambda: self.client.get_master_account(investor_id),
        )
        balance = self._check(
            "get_account_balance",
            "GET",
            f"/{prefix}/account_balances/{investor_id}",
            lambda: self.client.get_account_balance(investor_id),
        )
        margins = self._check(
            "list_margin_portfolios",
            "GET",
            f"/{prefix}/investors/{investor_id}/derivative_margin_portfolios",
            lambda: self.client.list_margin_portfolios(investor_id),
        )
        derivatives = self._check(
            "list_derivatives",
            "GET",
            f"/{prefix}/derivatives",
            self.client.list_derivatives,
        )

        investor_account_id = self._first_value(
            (balance, master),
            "investorAccountId",
        )
        margin_portfolio = self._first_record(margins)
        derivative = self._find_derivative(derivatives, symbol)

        if margin_portfolio and derivative:
            selected_symbol = derivative.get("symbol")
            price = derivative.get("marketPrice") or derivative.get("basicPrice")
            if selected_symbol is not None and price is not None:
                self._check(
                    "get_buying_power",
                    "GET",
                    f"/{prefix}/derivative/investors/{investor_id}/ppse",
                    lambda: self.client.get_buying_power(
                        investor_id=investor_id,
                        margin_portfolio_id=margin_portfolio["id"],
                        symbol=selected_symbol,
                        side="NB",
                        price=price,
                    ),
                )
            else:
                self._skip(
                    "get_buying_power", "The selected derivative has no usable symbol or price"
                )
        else:
            reason = (
                "The requested derivative was not returned"
                if symbol
                else "No margin portfolio or derivative was returned"
            )
            self._skip("get_buying_power", reason)

        orders = None
        deals = None
        risk_config = None
        if investor_account_id is not None:
            orders = self._check(
                "list_orders",
                "GET",
                f"/{prefix}/derivative/orders",
                lambda: self.client.list_orders(investor_account_id=investor_account_id),
            )
            order = self._first_record(orders)
            if order and order.get("id") is not None:
                order_id = order["id"]
                self._check(
                    "get_existing_order",
                    "GET",
                    f"/{prefix}/derivative/orders/{order_id}",
                    lambda: self.client.get_order(order_id),
                )

            deals = self._check(
                "list_deals",
                "GET",
                f"/{prefix}/derivative/deals",
                lambda: self.client.list_deals(investor_account_id=investor_account_id),
            )
            risk_config = self._check(
                "get_risk_config",
                "GET",
                f"/{prefix}/risk_configs",
                lambda: self.client.get_risk_config(investor_account_id=investor_account_id),
            )
        else:
            for name in ("list_orders", "get_order", "list_deals", "get_risk_config"):
                self._skip(name, "No investorAccountId was returned")

        return {
            "investor_account_id": investor_account_id,
            "margin_portfolio": margin_portfolio,
            "derivative": derivative,
            "orders": orders,
            "deals": deals,
            "risk_config": risk_config,
        }

    def _run_order_cancel(self, investor_id: int | str, context: dict[str, Any]) -> None:
        order_inputs = self._order_inputs(context)
        if order_inputs is None:
            self._skip("place_order", "Missing account, margin portfolio, or derivative data")
            self._skip("cancel_order", "No test order was submitted")
            return

        derivative = order_inputs["derivative"]
        price = derivative.get("floorPrice") or derivative.get("basicPrice")
        if price is None:
            self._skip("place_order", "The selected derivative has no valid test price")
            self._skip("cancel_order", "No test order was submitted")
            return
        placed = self._check(
            "place_order",
            "POST",
            f"/{self.client.api_prefix}/derivative/orders",
            lambda: self.client.place_order(
                investor_id=investor_id,
                margin_portfolio_id=order_inputs["margin_portfolio_id"],
                symbol=order_inputs["symbol"],
                side="NB",
                order_type="LO",
                quantity=1,
                price=price,
            ),
        )
        order_id = placed.get("id") if isinstance(placed, dict) else None
        if order_id is None:
            self._skip("cancel_order", "The test order did not return an order ID")
            return

        order = self._check(
            "get_order",
            "GET",
            f"/{self.client.api_prefix}/derivative/orders/{order_id}",
            lambda: self.client.get_order(order_id),
        )
        status = order.get("orderStatus") if isinstance(order, dict) else None
        if status in {"Filled", "PartiallyFilled"}:
            self._skip(
                "cancel_order", f"Test order reached {status}; inspect and close its demo deal"
            )
            return
        self._check(
            "cancel_order",
            "DELETE",
            f"/{self.client.api_prefix}/derivative/orders/{order_id}",
            lambda: self.client.cancel_order(order_id),
        )
        self._check(
            "get_canceled_order",
            "GET",
            f"/{self.client.api_prefix}/derivative/orders/{order_id}",
            lambda: self.client.get_order(order_id),
        )

    def _run_order_type_audit(self, investor_id: int | str, context: dict[str, Any]) -> None:
        order_inputs = self._order_inputs(context)
        if order_inputs is None:
            for order_type in AUDITED_ORDER_TYPES:
                self._skip(
                    f"{order_type.lower()}_place_fill_order",
                    "Missing account, margin portfolio, or derivative data",
                )
            return

        initial_deals = context.get("deals")
        if self._active_deals(initial_deals, symbol=order_inputs["symbol"]):
            for order_type in AUDITED_ORDER_TYPES:
                self._skip(
                    f"{order_type.lower()}_place_fill_order",
                    "An active deal already exists for the audit symbol",
                )
            return

        for order_type in AUDITED_ORDER_TYPES:
            if not self._run_fill_close_case(
                investor_id,
                order_inputs=order_inputs,
                order_type=order_type,
            ):
                for skipped_type in AUDITED_ORDER_TYPES[
                    AUDITED_ORDER_TYPES.index(order_type) + 1 :
                ]:
                    self._skip(
                        f"{skipped_type.lower()}_place_fill_order",
                        f"Stopped after the {order_type} case failed",
                    )
                return

    def _run_fill_close_case(
        self,
        investor_id: int | str,
        *,
        order_inputs: dict[str, Any],
        order_type: str,
    ) -> bool:
        name = order_type.lower()
        derivative = order_inputs["derivative"]
        price = derivative.get("ceilingPrice") or derivative.get("marketPrice")
        if price is None:
            self._record_failure(
                f"{name}_place_fill_order",
                "POST",
                f"/{self.client.api_prefix}/derivative/orders",
                "The selected derivative has no valid test price",
            )
            return False

        order_price = price if order_type == "LO" else 0.0
        placed = self._check(
            f"{name}_place_fill_order",
            "POST",
            f"/{self.client.api_prefix}/derivative/orders",
            lambda: self.client.place_order(
                investor_id=investor_id,
                margin_portfolio_id=order_inputs["margin_portfolio_id"],
                symbol=order_inputs["symbol"],
                side="NB",
                order_type=order_type,
                quantity=1,
                price=order_price,
            ),
        )
        order_id = placed.get("id") if isinstance(placed, dict) else None
        if order_id is None:
            return False

        filled_order = self._check(
            f"{name}_verify_fill",
            "GET",
            f"/{self.client.api_prefix}/derivative/orders/{order_id}",
            lambda: self._wait_for_fill(
                order_id,
                order_type=order_type,
                symbol=order_inputs["symbol"],
                quantity=1,
            ),
        )
        if filled_order is None:
            self._cleanup_test_state(
                order_inputs=order_inputs,
                order_id=order_id,
                check_name=f"{name}_cleanup_after_fill_failure",
            )
            return False

        deals = self._check(
            f"{name}_verify_deal_created",
            "GET",
            f"/{self.client.api_prefix}/derivative/deals",
            lambda: self._wait_for_active_deal(
                investor_account_id=order_inputs["investor_account_id"],
                symbol=order_inputs["symbol"],
            ),
        )
        if not isinstance(deals, dict):
            self._cleanup_test_state(
                order_inputs=order_inputs,
                order_id=order_id,
                check_name=f"{name}_cleanup_after_deal_query_failure",
            )
            return False
        deal = self._active_deals(deals, symbol=order_inputs["symbol"])[0]
        if deal is None:
            return False
        deal_id = deal["id"]
        closed = self._check(
            f"{name}_close_deal",
            "POST",
            f"/{self.client.api_prefix}/derivative/deals/{deal_id}/_close_deal",
            lambda: self.client.close_deal(deal_id, order_type=order_type),
        )
        if closed is None:
            self._cleanup_test_state(
                order_inputs=order_inputs,
                order_id=order_id,
                check_name=f"{name}_cleanup_after_close_failure",
            )
            return False

        verified = self._check(
            f"{name}_verify_closed_deal",
            "GET",
            f"/{self.client.api_prefix}/derivative/deals",
            lambda: self._wait_for_closed_deal(
                investor_account_id=order_inputs["investor_account_id"],
                deal_id=deal_id,
            ),
        )
        if verified is None:
            self._cleanup_test_state(
                order_inputs=order_inputs,
                order_id=order_id,
                check_name=f"{name}_cleanup_after_close_verification_failure",
            )
            return False

        no_active_deals = self._check(
            f"{name}_verify_no_active_deal",
            "GET",
            f"/{self.client.api_prefix}/derivative/deals",
            lambda: self._verify_no_active_deals(
                investor_account_id=order_inputs["investor_account_id"],
                symbol=order_inputs["symbol"],
            ),
        )
        return no_active_deals is not None

    def _run_risk_config_update(self, investor_id: int | str, context: dict[str, Any]) -> None:
        investor_account_id = context.get("investor_account_id")
        original = self._first_record(context.get("risk_config"))
        cut_loss_rate = None
        if original is not None:
            cut_loss_rate = original.get("cutLossRate")
            if cut_loss_rate is None:
                cut_loss_rate = original.get("defaultCutLossRate")
        required = {
            "trailingEnabled",
            "autoIncreaseDealRate",
            "enableAutoDealDepositNoti",
        }
        if (
            investor_account_id is None
            or original is None
            or cut_loss_rate is None
            or not required <= original.keys()
        ):
            self._skip("update_risk_config", "The original risk config is incomplete")
            return

        toggled = not bool(original["trailingEnabled"])
        try:
            self._check(
                "update_risk_config",
                "PATCH",
                f"/{self.client.api_prefix}/risk_configs/{investor_account_id}",
                lambda: self.client.update_risk_config(
                    investor_id=investor_id,
                    investor_account_id=investor_account_id,
                    cut_loss_rate=cut_loss_rate,
                    trailing_enabled=toggled,
                    auto_increase_deal_rate=original["autoIncreaseDealRate"],
                    enable_auto_deal_deposit_notification=original["enableAutoDealDepositNoti"],
                ),
            )
            self._check(
                "verify_updated_risk_config",
                "GET",
                f"/{self.client.api_prefix}/risk_configs",
                lambda: self._verify_risk_config(
                    self.client.get_risk_config(investor_account_id=investor_account_id),
                    cut_loss_rate=cut_loss_rate,
                    trailing_enabled=toggled,
                ),
            )
        finally:
            self._check(
                "restore_risk_config",
                "PATCH",
                f"/{self.client.api_prefix}/risk_configs/{investor_account_id}",
                lambda: self.client.update_risk_config(
                    investor_id=investor_id,
                    investor_account_id=investor_account_id,
                    cut_loss_rate=cut_loss_rate,
                    trailing_enabled=original["trailingEnabled"],
                    auto_increase_deal_rate=original["autoIncreaseDealRate"],
                    enable_auto_deal_deposit_notification=original["enableAutoDealDepositNoti"],
                ),
            )
            self._check(
                "verify_restored_risk_config",
                "GET",
                f"/{self.client.api_prefix}/risk_configs",
                lambda: self._verify_risk_config(
                    self.client.get_risk_config(investor_account_id=investor_account_id),
                    cut_loss_rate=cut_loss_rate,
                    trailing_enabled=original["trailingEnabled"],
                ),
            )

    def _check(
        self,
        name: str,
        method: str,
        path: str,
        call: Callable[[], Any],
        *,
        sanitize: Callable[[Any], Any] | None = None,
    ) -> Any:
        try:
            payload = call()
        except EntradeApiError as exc:
            self._checks.append(
                {
                    "name": name,
                    "status": "failed",
                    "method": method,
                    "url": exc.url,
                    "status_code": exc.status_code,
                    "error": str(exc),
                    "payload": exc.payload,
                },
            )
            return None
        except Exception as exc:
            self._record_failure(name, method, path, str(exc))
            return None
        self._record_success(name, method, path, sanitize(payload) if sanitize else payload)
        return payload

    def _record_success(self, name: str, method: str, path: str, payload: Any) -> None:
        self._checks.append(
            {
                "name": name,
                "status": "passed",
                "method": method,
                "url": self.client.url_for(path),
                "payload": payload,
            },
        )

    def _record_failure(self, name: str, method: str, path: str, error: str) -> None:
        self._checks.append(
            {
                "name": name,
                "status": "failed",
                "method": method,
                "url": self.client.url_for(path),
                "error": error,
            },
        )

    def _skip(self, name: str, reason: str) -> None:
        self._checks.append({"name": name, "status": "skipped", "reason": reason})

    def _result(self, investor_id: int | str | None) -> dict[str, Any]:
        failures = sum(check["status"] == "failed" for check in self._checks)
        skipped = sum(check["status"] == "skipped" for check in self._checks)
        verdict = "failed" if failures else "incomplete" if skipped else "passed"
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "account": "demo",
            "investor_id": self._masked_identifier(investor_id),
            "verdict": verdict,
            "checks": self._checks,
        }

    @staticmethod
    def _first_record(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return None

    @classmethod
    def _find_derivative(
        cls,
        payload: Any,
        symbol: str | None,
    ) -> dict[str, Any] | None:
        if symbol is None:
            return cls._first_record(payload)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            return None
        return next(
            (
                item
                for item in payload["data"]
                if isinstance(item, dict) and item.get("symbol") == symbol
            ),
            None,
        )

    def _wait_for_fill(
        self,
        order_id: int | str,
        *,
        order_type: str,
        symbol: str,
        quantity: int,
    ) -> dict[str, Any]:
        for _ in range(10):
            order = self.client.get_order(order_id)
            if order.get("orderStatus") == "Filled":
                if order.get("orderType") != order_type:
                    raise ValueError(
                        f"Expected orderType={order_type}, received {order.get('orderType')}",
                    )
                if order.get("symbol") != symbol:
                    raise ValueError(f"Expected symbol={symbol}, received {order.get('symbol')}")
                if order.get("quantity") != quantity or order.get("fillQuantity") != quantity:
                    raise ValueError(
                        "Filled order quantity did not match the submitted quantity: "
                        f"quantity={order.get('quantity')}, "
                        f"fillQuantity={order.get('fillQuantity')}",
                    )
                return order
            if order.get("orderStatus") in TERMINAL_ORDER_STATUSES:
                raise ValueError(
                    f"{order_type} order reached {order.get('orderStatus')} before filling",
                )
            self._sleep(1.0)
        raise TimeoutError(
            f"{order_type} order did not fill during the 10-second audit polling window"
        )

    def _wait_for_active_deal(
        self,
        *,
        investor_account_id: int | str,
        symbol: str,
    ) -> dict[str, Any]:
        for _ in range(10):
            payload = self.client.list_deals(investor_account_id=investor_account_id)
            if self._active_deals(payload, symbol=symbol):
                return payload
            self._sleep(1.0)
        raise TimeoutError("Filled order did not create an active deal during the polling window")

    def _wait_for_closed_deal(
        self,
        *,
        investor_account_id: int | str,
        deal_id: int | str,
    ) -> dict[str, Any]:
        for _ in range(10):
            payload = self.client.list_deals(investor_account_id=investor_account_id)
            deal = next(
                (item for item in payload.get("data", []) if str(item.get("id")) == str(deal_id)),
                None,
            )
            if deal is not None and deal.get("status") == "CLOSED":
                return deal
            self._sleep(1.0)
        raise TimeoutError("Deal did not close during the 10-second audit polling window")

    def _verify_no_active_deals(
        self,
        *,
        investor_account_id: int | str,
        symbol: str,
    ) -> dict[str, Any]:
        payload = self.client.list_deals(investor_account_id=investor_account_id)
        active = self._active_deals(payload, symbol=symbol)
        if active:
            raise ValueError(f"{len(active)} active test deal(s) remain for {symbol}")
        return payload

    def _verify_safe_order_test_start(
        self,
        context: dict[str, Any],
        *,
        symbol: str,
    ) -> dict[str, Any]:
        orders = context.get("orders")
        deals = context.get("deals")
        if not isinstance(orders, dict) or not isinstance(orders.get("data"), list):
            raise ValueError("Order query did not return a usable data list")
        if not isinstance(deals, dict) or not isinstance(deals.get("data"), list):
            raise ValueError("Deal query did not return a usable data list")

        open_orders = [
            order
            for order in orders["data"]
            if isinstance(order, dict)
            and order.get("symbol") in {None, symbol}
            and order.get("orderStatus") not in TERMINAL_ORDER_STATUSES
        ]
        active_deals = self._active_deals(deals, symbol=symbol)
        if open_orders or active_deals:
            raise ValueError(
                f"Unsafe audit start: open_orders={len(open_orders)}, "
                f"active_deals={len(active_deals)}",
            )
        return {"orders": orders, "deals": deals}

    def _cleanup_test_state(
        self,
        *,
        order_inputs: dict[str, Any],
        order_id: int | str,
        check_name: str,
    ) -> None:
        def cleanup() -> dict[str, Any]:
            order = self.client.get_order(order_id)
            if order.get("orderStatus") not in TERMINAL_ORDER_STATUSES:
                self.client.cancel_order(order_id)

            deals = self.client.list_deals(
                investor_account_id=order_inputs["investor_account_id"],
            )
            for deal in self._active_deals(deals, symbol=order_inputs["symbol"]):
                self.client.close_deal(deal["id"], order_type="MTL")
                self._wait_for_closed_deal(
                    investor_account_id=order_inputs["investor_account_id"],
                    deal_id=deal["id"],
                )
            return self._verify_no_active_deals(
                investor_account_id=order_inputs["investor_account_id"],
                symbol=order_inputs["symbol"],
            )

        self._check(
            check_name,
            "POST",
            f"/{self.client.api_prefix}/derivative/deals/{{deal_id}}/_close_deal",
            cleanup,
        )

    @staticmethod
    def _active_deals(payload: Any, *, symbol: str) -> list[dict[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("Deal query did not return a usable data list")
        return [
            deal
            for deal in payload["data"]
            if isinstance(deal, dict)
            and deal.get("status") == "ACTIVE"
            and deal.get("symbol") == symbol
        ]

    @classmethod
    def _verify_risk_config(
        cls,
        payload: dict[str, Any],
        *,
        cut_loss_rate: float,
        trailing_enabled: bool,
    ) -> dict[str, Any]:
        record = cls._first_record(payload)
        if record is None:
            raise ValueError("Risk config query returned no record")
        actual_rate = record.get("cutLossRate")
        if actual_rate is None:
            actual_rate = record.get("defaultCutLossRate")
        if actual_rate != cut_loss_rate or record.get("trailingEnabled") != trailing_enabled:
            raise ValueError(
                "Risk config state did not match the requested values: "
                f"rate={actual_rate}, trailingEnabled={record.get('trailingEnabled')}",
            )
        return payload

    @staticmethod
    def _first_value(payloads: tuple[Any, ...], key: str) -> Any:
        for payload in payloads:
            if isinstance(payload, dict) and payload.get(key) is not None:
                return payload[key]
        return None

    @staticmethod
    def _masked_identifier(value: int | str | None) -> str | None:
        if value is None:
            return None
        text = str(value)
        return f"***{text[-4:]}" if len(text) > 4 else "***"

    @staticmethod
    def _order_inputs(context: dict[str, Any]) -> dict[str, Any] | None:
        account_id = context.get("investor_account_id")
        margin = context.get("margin_portfolio")
        derivative = context.get("derivative")
        if account_id is None or not isinstance(margin, dict) or not isinstance(derivative, dict):
            return None
        if margin.get("id") is None or derivative.get("symbol") is None:
            return None
        return {
            "investor_account_id": account_id,
            "margin_portfolio_id": margin["id"],
            "symbol": derivative["symbol"],
            "derivative": derivative,
        }
