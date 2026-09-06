from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from paycheck_map.plaid_client import JsonObject, PlaidAPIError, PlaidClient


def _client(responses: list[JsonObject], *, status: int = 200) -> PlaidClient:
    pages: Iterator[JsonObject] = iter(responses)
    return PlaidClient(
        environment="sandbox",
        client_id="synthetic",
        secret="synthetic",
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=next(pages))),
    )


@pytest.mark.parametrize(
    "raw_code,expected",
    [("PRIVATE-CODE", "PLAID_ERROR"), ("ITEM_LOGIN_REQUIRED", "ITEM_LOGIN_REQUIRED")],
)
def test_provider_error_text_is_not_treated_as_safe(raw_code: str, expected: str) -> None:
    client = _client(
        [
            {
                "error_code": raw_code,
                "display_message": "PRIVATE-DISPLAY",
                "error_message": "PRIVATE-ERROR",
            }
        ],
        status=400,
    )
    with pytest.raises(PlaidAPIError) as failure:
        client.item_get("synthetic-token")
    assert failure.value.code == expected
    assert "PRIVATE" not in str(failure.value)


def _sync_page(cursor: str, more: object) -> JsonObject:
    return {"next_cursor": cursor, "has_more": more, "added": [], "modified": [], "removed": []}


def test_repeated_sync_cursor_rejects_partial_history() -> None:
    client = _client([_sync_page("same", True), _sync_page("same", True)])
    with pytest.raises(PlaidAPIError, match="incomplete"):
        client.transactions_sync("synthetic-token", None)


@pytest.mark.parametrize(
    "page", [{}, _sync_page("cursor", "false"), {"next_cursor": "cursor", "has_more": False}]
)
def test_malformed_sync_history_is_not_empty_success(page: JsonObject) -> None:
    with pytest.raises(PlaidAPIError):
        _client([page]).transactions_sync("synthetic-token", None)


def test_sync_history_accepts_complete_multi_page_result() -> None:
    pages = [_sync_page("first", True), _sync_page("last", False)]
    assert _client(pages).transactions_sync("synthetic-token", None) == pages


@pytest.mark.parametrize("investments", [False, True])
@pytest.mark.parametrize(
    "rows,total", [(None, 0), ([], 1), ([], "0"), ([], True), ([], -1), ([{}], 0)]
)
def test_invalid_offset_history_never_returns_partial_success(
    investments: bool, rows: object, total: object
) -> None:
    key = "investment_transactions" if investments else "transactions"
    client = _client([{key: rows, f"total_{key}": total}])
    method = client.investments_transactions_get if investments else client.transactions_get
    with pytest.raises(PlaidAPIError):
        method("synthetic-token")


@pytest.mark.parametrize("investments", [False, True])
def test_complete_offset_history_and_empty_history(investments: bool) -> None:
    key = "investment_transactions" if investments else "transactions"
    for pages in [
        [{key: [], f"total_{key}": 0}],
        [{key: [{}], f"total_{key}": 2}, {key: [{}], f"total_{key}": 2}],
    ]:
        client = _client(pages)
        method = client.investments_transactions_get if investments else client.transactions_get
        assert method("synthetic-token") == pages


def test_pagination_has_a_finite_page_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("paycheck_map.plaid_client.MAX_HISTORY_PAGES", 2)
    with pytest.raises(PlaidAPIError):
        _client([_sync_page("one", True), _sync_page("two", True)]).transactions_sync(
            "synthetic-token", None
        )
