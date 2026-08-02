from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paycheck_map.config import Settings
from paycheck_map.forecasting import ScenarioInput, build_forecast
from paycheck_map.ingestion import import_private_inbox, rollback_import_batch
from paycheck_map.models import (
    Account,
    AccountBalancePoint,
    ForecastScenario,
    ImportArtifact,
    InvestmentValueBridge,
    PayrollLineItem,
    PayrollStatement,
    ReconciliationResult,
    TransferMatch,
)
from paycheck_map.reporting import generate_trailing_report
from paycheck_map.services import account_detail, accounts_dashboard, exceptions, overview, timeline


def test_import_reconcile_forecast_report_and_rollback(
    session: Session,
    runtime_settings: Settings,
    populated_inbox: Path,
) -> None:
    del populated_inbox
    first = import_private_inbox(session, runtime_settings)
    assert first.discovered == 4
    assert first.imported == 4
    assert not first.errors

    second = import_private_inbox(session, runtime_settings)
    assert second.imported == 0
    assert second.duplicates == 4
    assert session.scalar(select(func.count(ImportArtifact.id))) == 4

    statement = session.scalar(select(PayrollStatement))
    assert statement is not None
    assert statement.detail_complete
    assert statement.observed_deposit_date == date(2026, 7, 1)
    assert (session.scalar(select(func.count(PayrollLineItem.id))) or 0) > 6
    arithmetic = session.scalar(
        select(ReconciliationResult).where(
            ReconciliationResult.entity_type == "payroll_statement",
            ReconciliationResult.entity_id == str(statement.id),
            ReconciliationResult.rule == "payroll_arithmetic",
        )
    )
    assert arithmetic is not None
    assert arithmetic.status == "reconciled"
    assert arithmetic.residual == Decimal("0.00")
    detail_rules = set(
        session.scalars(
            select(ReconciliationResult.rule).where(
                ReconciliationResult.entity_type == "payroll_statement",
                ReconciliationResult.entity_id == str(statement.id),
                ReconciliationResult.rule.like("%_detail"),
            )
        )
    )
    assert {
        "earnings_detail",
        "pretax_detail",
        "tax_detail",
        "after_tax_detail",
        "net_distribution_detail",
        "destination_detail",
    } <= detail_rules

    summary = overview(session)
    assert summary["latest_payroll_baseline"]["observed_deposit_date"] == date(2026, 7, 1)
    assert summary["annual_snapshots"][0]["employee_retirement"] == "7595.35"
    assert summary["annual_snapshots"][0]["health_premiums"] == "1550.88"
    assert summary["annual_snapshots"][0]["stock_offset"] == "5206.40"
    assert summary["recurring_paycheck"]["net_payment"] == "3765.83"
    assert summary["recurring_paycheck"]["employee_retirement"] == "438.46"
    assert summary["recurring_paycheck"]["employer_retirement"] == "255.77"
    assert len(summary["recurring_paycheck"]["deposit_splits"]) == 2
    assert not {
        "destination_detail",
        "pay_period_continuity",
        "ytd_roll_forward",
        "payroll_to_sofi",
    } & {issue["rule"] for issue in exceptions(session)}

    assert session.scalar(select(func.count(Account.id))) == 3
    assert session.scalar(select(func.count(TransferMatch.id))) == 1
    bridge = session.scalar(select(InvestmentValueBridge))
    assert bridge is not None
    assert bridge.investment_result == Decimal("150.00")

    account_view = accounts_dashboard(session)
    assert account_view["totals"] == {
        "net_worth": "13802.00",
        "assets": "13802.00",
        "debts": "0.00",
        "cash": "2802.00",
        "investments": "11000.00",
        "money_in": "2002.00",
        "money_out": "700.00",
        "net_cash_flow": "1302.00",
    }
    assert {row["category"] for row in account_view["accounts"]} == {"cash", "investment"}
    assert (session.scalar(select(func.count(AccountBalancePoint.id))) or 0) >= 4
    investment = next(row for row in account_view["accounts"] if row["category"] == "investment")
    detail = account_detail(
        session,
        investment["id"],
        date(2026, 1, 1),
        date(2026, 1, 31),
    )
    assert detail is not None
    assert detail["performance_status"] == "available"
    assert detail["bridges"][0]["investment_result"] == "150.00"
    month = timeline(session, date(2026, 1, 1), date(2026, 1, 31))[0]
    assert month["investment_contributions"] == "850.00"
    assert month["investment_result"] == "150.00"

    baseline = build_forecast(
        session,
        ScenarioInput(name="No-change baseline"),
        runtime_settings,
        is_baseline=True,
        as_of=date(2026, 7, 25),
    )
    alternative = build_forecast(
        session,
        ScenarioInput(
            name="Synthetic comparison",
            additional_401k_pct=Decimal("2"),
            checking_split_pct=Decimal("80"),
            monthly_outflow=Decimal("1000"),
        ),
        runtime_settings,
        as_of=date(2026, 7, 25),
    )
    assert baseline.annual_salary == Decimal("190000.00")
    assert baseline.additional_fidelity_funding == Decimal("0.00")
    assert alternative.additional_fidelity_funding > Decimal("0.00")
    scenario = session.get(ForecastScenario, alternative.scenario_id)
    assert scenario is not None
    assert len(scenario.periods) == 12
    assert scenario.inputs["pay_schedule_anchor"] == "2026-07-01"
    assert scenario.inputs["assumption_warnings"]
    assert any("2027" in warning for warning in alternative.contribution_limit_warnings)

    replacement = build_forecast(
        session,
        ScenarioInput(
            name="Synthetic comparison",
            additional_401k_pct=Decimal("3"),
        ),
        runtime_settings,
        as_of=date(2026, 7, 25),
    )
    assert replacement.additional_fidelity_funding > alternative.additional_fidelity_funding
    assert (
        session.scalar(
            select(func.count(ForecastScenario.id)).where(
                ForecastScenario.name == "Synthetic comparison"
            )
        )
        == 1
    )

    first_report = generate_trailing_report(session, runtime_settings).read_bytes()
    second_report = generate_trailing_report(session, runtime_settings).read_bytes()
    assert first_report == second_report
    assert b"Synthetic Employer" not in first_report
    assert b"Gross pay accounted for" in first_report
    assert b"difference: $0.00" in first_report

    assert rollback_import_batch(session, first.batch_id)
    assert session.scalar(select(func.count(ImportArtifact.id))) == 0
    assert session.scalar(select(func.count(ForecastScenario.id))) == 0
