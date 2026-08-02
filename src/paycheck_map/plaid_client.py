from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

JsonObject = dict[str, Any]


class PlaidAPIError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        request_id: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.request_id = request_id
        self.status_code = status_code


class PlaidClient:
    """Small read-only Plaid API client with safe error surfaces."""

    def __init__(
        self,
        *,
        environment: str,
        client_id: str,
        secret: str,
        timeout: float = 45.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if environment not in {"sandbox", "production"}:
            raise ValueError("Plaid environment must be sandbox or production")
        self.base_url = f"https://{environment}.plaid.com"
        self.headers = {
            "PLAID-CLIENT-ID": client_id,
            "PLAID-SECRET": secret,
            "Content-Type": "application/json",
        }
        self.timeout = timeout
        self.transport = transport

    def _post(self, endpoint: str, payload: JsonObject) -> JsonObject:
        try:
            with httpx.Client(
                base_url=self.base_url,
                headers=self.headers,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = client.post(endpoint, json=payload)
        except httpx.RequestError as exc:
            raise PlaidAPIError(
                code="NETWORK_ERROR",
                message="Plaid could not be reached from this Mac.",
            ) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise PlaidAPIError(
                code="INVALID_RESPONSE",
                message="Plaid returned an unreadable response.",
                status_code=response.status_code,
            ) from exc
        if not isinstance(body, dict):
            raise PlaidAPIError(
                code="INVALID_RESPONSE",
                message="Plaid returned an unexpected response.",
                status_code=response.status_code,
            )
        if response.is_error:
            code = str(body.get("error_code") or "PLAID_ERROR")
            display = body.get("display_message")
            generic = body.get("error_message")
            message = str(display or generic or "Plaid rejected the request.")
            raise PlaidAPIError(
                code=code,
                message=message[:500],
                request_id=_optional_text(body.get("request_id")),
                status_code=response.status_code,
            )
        return body

    def create_link_token(self, *, target: str, client_user_id: str) -> JsonObject:
        products = ["transactions"] if target == "sofi" else ["investments"]
        payload: JsonObject = {
            "client_name": "Paycheck Map",
            "country_codes": ["US"],
            "language": "en",
            "products": products,
            "user": {"client_user_id": client_user_id},
        }
        if target == "sofi":
            payload["transactions"] = {"days_requested": 730}
        return self._post(
            "/link/token/create",
            payload,
        )

    def create_update_link_token(self, *, access_token: str, client_user_id: str) -> JsonObject:
        return self._post(
            "/link/token/create",
            {
                "client_name": "Paycheck Map",
                "country_codes": ["US"],
                "language": "en",
                "access_token": access_token,
                "user": {"client_user_id": client_user_id},
            },
        )

    def exchange_public_token(self, public_token: str) -> JsonObject:
        return self._post("/item/public_token/exchange", {"public_token": public_token})

    def item_get(self, access_token: str) -> JsonObject:
        return self._post("/item/get", {"access_token": access_token})

    def institution_get(self, institution_id: str) -> JsonObject:
        return self._post(
            "/institutions/get_by_id",
            {
                "institution_id": institution_id,
                "country_codes": ["US"],
                "options": {"include_optional_metadata": False},
            },
        )

    def accounts_balance_get(self, access_token: str) -> JsonObject:
        return self._post("/accounts/balance/get", {"access_token": access_token})

    def transactions_sync(self, access_token: str, cursor: str | None) -> list[JsonObject]:
        pages: list[JsonObject] = []
        next_cursor = cursor
        while True:
            payload: JsonObject = {
                "access_token": access_token,
                "count": 500,
                "options": {"include_original_description": True},
            }
            if next_cursor:
                payload["cursor"] = next_cursor
            response = self._post("/transactions/sync", payload)
            pages.append(response)
            next_cursor = _optional_text(response.get("next_cursor"))
            if not bool(response.get("has_more")):
                return pages

    def transactions_get(
        self,
        access_token: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[JsonObject]:
        """Fetch the complete history currently authorized for an existing Item."""

        end = end_date or date.today()
        start = start_date or end - timedelta(days=730)
        pages: list[JsonObject] = []
        offset = 0
        while True:
            response = self._post(
                "/transactions/get",
                {
                    "access_token": access_token,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "options": {
                        "count": 500,
                        "offset": offset,
                        "include_original_description": True,
                    },
                },
            )
            pages.append(response)
            rows = response.get("transactions")
            row_count = len(rows) if isinstance(rows, list) else 0
            total = int(response.get("total_transactions") or row_count)
            offset += row_count
            if row_count == 0 or offset >= total:
                return pages

    def investments_holdings_get(self, access_token: str) -> JsonObject:
        return self._post("/investments/holdings/get", {"access_token": access_token})

    def investments_transactions_get(
        self,
        access_token: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[JsonObject]:
        end = end_date or date.today()
        start = start_date or end - timedelta(days=730)
        pages: list[JsonObject] = []
        offset = 0
        while True:
            response = self._post(
                "/investments/transactions/get",
                {
                    "access_token": access_token,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "options": {"count": 500, "offset": offset},
                },
            )
            pages.append(response)
            rows = response.get("investment_transactions")
            row_count = len(rows) if isinstance(rows, list) else 0
            total = int(response.get("total_investment_transactions") or row_count)
            offset += row_count
            if row_count == 0 or offset >= total:
                return pages

    def remove_item(self, access_token: str) -> JsonObject:
        return self._post("/item/remove", {"access_token": access_token})


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
