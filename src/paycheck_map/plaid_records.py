"""Pure Plaid payload parsing and classification; no credentials, database or network writes."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .business_time import as_utc
from .money import ZERO, money
from .plaid_client import JsonObject


def sofi_role(row: JsonObject, amount: Decimal) -> str:
    description = " ".join(
        value
        for value in (
            optional_text(row.get("name")),
            optional_text(row.get("merchant_name")),
            optional_text(row.get("original_description")),
        )
        if value
    ).upper()
    category = object_fields(row.get("personal_finance_category"))
    primary = (optional_text(category.get("primary")) or "").upper()
    detailed = (optional_text(category.get("detailed")) or "").upper()
    owned_transfer_markers = (
        "FROM SAVINGS",
        "TO SAVINGS",
        "FROM CHECKING",
        "TO CHECKING",
    )
    if "PAYROLL" in description or detailed == "INCOME_WAGES":
        return "payroll_deposit"
    if "INTEREST" in description or detailed == "INCOME_INTEREST_EARNED":
        return "interest"
    if primary == "BANK_FEES" or "FEE" in detailed:
        return "fee"
    if any(marker in description for marker in owned_transfer_markers) or (
        "FIDELITY" in description and primary in {"TRANSFER_IN", "TRANSFER_OUT"}
    ):
        return "internal_transfer"
    return "external_inflow" if amount >= ZERO else "external_outflow"


def fidelity_role(row: JsonObject, description: str) -> tuple[str, str]:
    transaction_type = (optional_text(row.get("type")) or "").lower()
    subtype = (optional_text(row.get("subtype")) or "").lower()
    label = description.upper()
    if "REALIZEDGAINLOSS" in label.replace(" ", ""):
        return "adjustment", "high"
    if "EMPLOYER" in label and ("MATCH" in label or "CONTRIB" in label):
        return "employer_contribution", "medium"
    if "EMPLOYEE" in label and "CONTRIB" in label:
        return "employee_contribution", "medium"
    if transaction_type == "buy":
        return "purchase", "high"
    if transaction_type == "sell":
        return "sale", "high"
    if subtype in {"dividend", "qualified dividend", "non-qualified dividend"}:
        return "dividend", "high"
    if subtype == "interest":
        return "interest", "high"
    if transaction_type == "fee" or "fee" in subtype:
        return "fee", "high"
    if transaction_type == "transfer" or any(
        marker in label
        for marker in (
            "TRANSFERRED TO",
            "TRANSFERRED FROM",
            "TRANSFER TO FIDELITY",
            "FIDELITY CRYPTO",
        )
    ):
        return "internal_transfer", "medium"
    if (
        "ESPP" in label
        or "STOCK PLAN" in label
        or "SPP PURCHASE CREDIT" in label
        or "JOURNALED SPP" in label
    ) and subtype in {
        "contribution",
        "deposit",
    }:
        return "stock_plan_contribution", "medium"
    if subtype in {"contribution", "deposit"}:
        return "external_deposit", "high"
    if subtype in {"withdrawal"}:
        return "external_withdrawal", "high"
    if subtype == "reinvestment":
        return "reinvestment", "high"
    return "unresolved", "low"


def account_display_name(row: JsonObject) -> str:
    name = (
        optional_text(row.get("official_name"))
        or optional_text(row.get("name"))
        or "Connected account"
    )
    mask = optional_text(row.get("mask"))
    return f"{name} ••{mask}" if mask else name


def object_records(value: object) -> list[JsonObject]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Plaid returned invalid record collections")
    return value


def object_fields(value: object) -> JsonObject:
    return value if isinstance(value, dict) else {}


def list_count(response: JsonObject, key: str) -> int:
    value = response.get(key)
    return len(value) if isinstance(value, list) else 0


def required_text(row: JsonObject, key: str) -> str:
    value = optional_text(row.get(key))
    if not value:
        raise ValueError(f"Plaid response is missing {key}")
    return value


def optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def decimal_amount(value: object) -> Decimal:
    if value is None:
        raise ValueError("Plaid returned a missing required amount")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise ValueError("Plaid returned a non-finite amount")
        return amount
    except InvalidOperation as exc:
        raise ValueError("Plaid returned a non-numeric amount") from exc


def money_amount(value: object) -> Decimal:
    return money(decimal_amount(value))


def optional_money(value: object) -> Decimal | None:
    return None if value is None else money_amount(value)


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Plaid returned an invalid date") from error


def parse_datetime(value: str) -> datetime:
    try:
        return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as error:
        raise ValueError("Plaid returned an invalid timestamp") from error


def optional_datetime(value: object) -> datetime | None:
    text = optional_text(value)
    return parse_datetime(text) if text else None
