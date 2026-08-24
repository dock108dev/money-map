"""Stable facade for read-only API projection services."""

from .service_accounts import account_detail, accounts_dashboard
from .service_common import amount, latest_complete_period
from .service_overview import overview
from .service_payroll import paychecks, payroll_entry, payroll_history, payroll_reconciliation
from .service_summaries import (
    exceptions,
    fidelity_summary,
    imports,
    scenarios,
    sofi_summary,
    timeline,
)
from .service_wealth import wealth_dashboard

__all__ = [
    "account_detail",
    "accounts_dashboard",
    "amount",
    "exceptions",
    "fidelity_summary",
    "imports",
    "latest_complete_period",
    "overview",
    "paychecks",
    "payroll_entry",
    "payroll_history",
    "payroll_reconciliation",
    "scenarios",
    "sofi_summary",
    "timeline",
    "wealth_dashboard",
]
