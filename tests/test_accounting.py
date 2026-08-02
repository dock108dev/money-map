from __future__ import annotations

from decimal import Decimal

from paycheck_map.money import money
from paycheck_map.reconciliation import fidelity_investment_result, sofi_balance_residual


def test_money_quantizes_without_binary_float() -> None:
    assert money("10.005") == Decimal("10.01")
    assert money(10) == Decimal("10.00")


def test_sofi_balance_equation() -> None:
    assert sofi_balance_residual(
        Decimal("100.00"),
        [Decimal("25.00"), Decimal("-10.00")],
        Decimal("115.00"),
    ) == Decimal("0.00")


def test_fidelity_result_excludes_external_flows() -> None:
    result = fidelity_investment_result(
        opening_value=Decimal("10000.00"),
        closing_value=Decimal("11000.00"),
        employee_contributions=Decimal("500.00"),
        employer_contributions=Decimal("250.00"),
        stock_plan_contributions=Decimal("100.00"),
    )
    assert result == Decimal("150.00")
