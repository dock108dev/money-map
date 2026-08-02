from __future__ import annotations

from html import escape
from pathlib import Path

from sqlalchemy.orm import Session

from .config import Settings, settings
from .forecasting import ensure_baseline
from .services import accounts_dashboard, overview, scenarios, timeline


def _money(value: object) -> str:
    return "—" if value in (None, "") else f"${escape(str(value))}"


def generate_trailing_report(session: Session, runtime_settings: Settings = settings) -> Path:
    """Create the deterministic, print-friendly Money Map for the default period."""

    ensure_baseline(session, runtime_settings)
    summary = overview(session)
    accounts = accounts_dashboard(session)
    period = summary["period"]
    months = timeline(session, period["start"], period["end"])
    forecast_rows = scenarios(session)
    baseline = next((row for row in forecast_rows if row["is_baseline"]), None)
    alternative = next((row for row in forecast_rows if not row["is_baseline"]), None)

    gross_destination_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['label']))}</td>"
        f"<td>{escape(str(row['section']).replace('_', ' ').title())}</td>"
        f"<td>{_money(row['amount'])}</td>"
        "</tr>"
        for row in summary["allocation"]["destinations"]
        if row["section"] not in {"compensation", "employer"}
    )
    employer_destination_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['label']))}</td>"
        f"<td>{escape(str(row['section']).replace('_', ' ').title())}</td>"
        f"<td>{_money(row['amount'])}</td>"
        "</tr>"
        for row in summary["allocation"]["destinations"]
        if row["section"] == "employer"
    )
    month_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['month']))}</td>"
        f"<td>{_money(row.get('gross_pay'))}</td>"
        f"<td>{_money(row.get('taxes'))}</td>"
        f"<td>{_money(row.get('net_pay'))}</td>"
        f"<td>{_money(row.get('cash_inflows'))}</td>"
        f"<td>{_money(row.get('cash_outflows'))}</td>"
        f"<td>{_money(row.get('investment_contributions'))}</td>"
        f"<td>{_money(row.get('investment_result'))}</td>"
        "</tr>"
        for row in months
    )
    account_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['name']))}</td>"
        f"<td>{escape(str(row['category']).title())}</td>"
        f"<td>{_money(row['current_balance'])}</td>"
        f"<td>{_money(row['change'])}</td>"
        "</tr>"
        for row in accounts["accounts"]
    )

    def forecast_table(scenario: dict[str, object] | None) -> str:
        if scenario is None:
            return ""
        periods = scenario["periods"]
        assert isinstance(periods, list)
        rows = "".join(
            "<tr>"
            f"<td>{escape(str(row['month']))}</td>"
            f"<td>{_money(row['gross_pay'])}</td>"
            f"<td>{_money(row['employee_retirement'])}</td>"
            f"<td>{_money(row['stock_plan'])}</td>"
            f"<td>{_money(row['cash_redirect_to_investments'])}</td>"
            f"<td>{_money(row['ending_cash'])}</td>"
            f"<td>{_money(row['assumed_investment_result'])}</td>"
            "</tr>"
            for row in periods
            if isinstance(row, dict)
        )
        return (
            f"<h3>{escape(str(scenario['name']))}</h3>"
            "<table><thead><tr><th>Month</th><th>Gross</th><th>401(k)</th>"
            "<th>Stock plan</th><th>Cash redirect</th><th>Ending cash</th>"
            "<th>Assumed result</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    totals = summary["totals"]
    allocation_reconciliation = summary["allocation"]["reconciliation"]
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Money Map</title>
<style>
body{{font-family:system-ui,sans-serif;color:#17231f;margin:40px;line-height:1.4}}
h1{{margin-bottom:4px}} h2{{margin-top:32px}} .muted{{color:#5d6b65}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}}
.card{{border:1px solid #d9e1dc;border-radius:12px;padding:16px}}
.value{{font-size:22px;font-weight:700}}
table{{width:100%;border-collapse:collapse;margin:12px 0 24px}}
th,td{{padding:9px;border-bottom:1px solid #e1e6e3;text-align:right;font-size:13px}}
th:first-child,td:first-child{{text-align:left}}
.source{{font-size:12px;color:#64716b}}
@media print{{body{{margin:14mm}} .cards{{grid-template-columns:repeat(2,1fr)}} h2{{break-after:avoid}}}}
</style>
</head>
<body>
<h1>Money Map</h1>
<p class="muted">{escape(str(period["start"]))} through {escape(str(period["end"]))} · balances as of {escape(str(accounts["as_of"]))}</p>
<div class="cards">
<div class="card"><div>Net worth</div><div class="value">{_money(accounts["totals"]["net_worth"])}</div></div>
<div class="card"><div>Gross compensation</div><div class="value">{_money(totals["gross_compensation"])}</div></div>
<div class="card"><div>Taxes</div><div class="value">{_money(totals["taxes"])}</div></div>
<div class="card"><div>Net pay</div><div class="value">{_money(totals["net_payments"])}</div></div>
</div>
<h2>Paycheck allocation</h2>
<table><thead><tr><th>Destination</th><th>Section</th><th>Amount</th></tr></thead><tbody>{gross_destination_rows}</tbody></table>
<p class="source">Gross pay accounted for: {_money(allocation_reconciliation["accounted_from_gross"])} · difference: {_money(allocation_reconciliation["residual"])}</p>
<h3>Employer-paid additions</h3>
<p class="source">Additional money that is not deducted from gross pay.</p>
<table><thead><tr><th>Destination</th><th>Section</th><th>Amount</th></tr></thead><tbody>{employer_destination_rows}</tbody></table>
<h2>Month by month</h2>
<table><thead><tr><th>Month</th><th>Gross</th><th>Taxes</th><th>Net pay</th><th>Cash in</th><th>Cash out</th><th>Investment deposits</th><th>Investment result</th></tr></thead><tbody>{month_rows}</tbody></table>
<h2>Accounts</h2>
<table><thead><tr><th>Account</th><th>Type</th><th>Current value</th><th>Tracked change</th></tr></thead><tbody>{account_rows}</tbody></table>
<h2>12-month plan</h2>
{forecast_table(baseline)}
{forecast_table(alternative)}
<p class="source">Statement values remain immutable. Calculated payroll allocations and reconstructed balances use versioned deterministic arithmetic. Investment result appears only for a period with two dated value observations. Assumed forecast returns are separate from contributions.</p>
</body></html>"""
    runtime_settings.reports_dir.mkdir(parents=True, exist_ok=True)
    output = runtime_settings.reports_dir / "trailing-12-month-money-map.html"
    output.write_text(html, encoding="utf-8")
    return output
