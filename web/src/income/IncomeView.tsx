import { useState } from "react";

import { currency, currencyExact, shortDate } from "../format";
import type { PayrollEntry, PayrollHistory } from "../types";
import { EmptyState, MetricCard, roleLabel } from "../ui-primitives";

const toCents = (value: string | null | undefined) =>
  value == null ? 0 : Math.round(Number(value) * 100);

const fromCents = (value: number) => (value / 100).toFixed(2);

export function IncomeView({ data }: { data: PayrollHistory }) {
  const [startDate, setStartDate] = useState(data.period.start);
  const [endDate, setEndDate] = useState(data.period.end);
  const [selected, setSelected] = useState<PayrollEntry | null>(null);
  const rows = data.rows.filter(
    (row) => row.observed_deposit_date >= startDate && row.observed_deposit_date <= endDate,
  );
  const sum = (field: keyof Pick<
    PayrollEntry,
    | "gross_earnings"
    | "pretax_deductions"
    | "tax_withholdings"
    | "after_tax_deductions"
    | "net_payment"
    | "employee_account_funding"
    | "employer_account_funding"
    | "total_paycheck_value"
  >) => fromCents(rows.reduce((total, row) => total + toCents(row[field]), 0));
  const hasImportedPaychecks = data.rows.length > 0;

  return (
    <div className="view-stack account-first-view">
      <section className="simple-page-heading income-heading" data-copy-budget="utility-page-heading">
        <div>
          <span className="eyebrow">Every other Wednesday</span>
          <h1 data-prose>Income</h1>
        </div>
        <strong>{rows.length} paychecks</strong>
      </section>
      {hasImportedPaychecks && <div className="date-range" aria-label="Income date range">
        <label>
          From
          <input
            type="date"
            min={data.period.start}
            max={endDate}
            value={startDate}
            onChange={(event) => setStartDate(event.currentTarget.value)}
            onInput={(event) => setStartDate(event.currentTarget.value)}
          />
        </label>
        <label>
          Through
          <input
            type="date"
            min={startDate}
            max={data.period.end}
            value={endDate}
            onChange={(event) => setEndDate(event.currentTarget.value)}
            onInput={(event) => setEndDate(event.currentTarget.value)}
          />
        </label>
      </div>}
      {rows.length === 0 ? (
        <section className="panel compact-panel empty-state" role="status">
          <h2>{hasImportedPaychecks ? "No paychecks in this period" : "Income unavailable"}</h2>
          <p>
            {hasImportedPaychecks
              ? "Choose a date range that includes imported paycheck evidence."
              : "No paycheck evidence has been imported. Use Add account to import a payroll statement, then return to Income."}
          </p>
        </section>
      ) : <><section className="overview-metrics income-metrics">
        <MetricCard label="Gross" value={currencyExact(sum("gross_earnings"))} />
        <MetricCard label="Spendable cash" value={currencyExact(sum("net_payment"))} tone="green" />
        <MetricCard label="Your account funding" value={currencyExact(sum("employee_account_funding"))} />
        <MetricCard label="Employer additions" value={currencyExact(sum("employer_account_funding"))} />
        <MetricCard label="Total paycheck value" value={currencyExact(sum("total_paycheck_value"))} tone="ink" />
      </section>
      <section className="panel compact-panel">
        <div className="payroll-list">
          {rows.map((row) => (
            <button className="payroll-row" key={row.id} onClick={() => setSelected(row)}>
              <span className={`payroll-source source-${row.source_kind}`}>
                {row.source_kind === "statement" ? "Statement" : "Calculated"}
              </span>
              <span className="payroll-date">
                <strong>{shortDate(row.observed_deposit_date)}</strong>
                <small>Official {shortDate(row.payment_date)}</small>
              </span>
              <span className="payroll-role">
                <strong>{row.job_title ?? row.employer}</strong>
                <small>{currency(row.base_salary)} salary</small>
              </span>
              <span className="payroll-gross">
                <small>Spendable</small>
                <strong>{currencyExact(row.net_payment)}</strong>
              </span>
              <span className="payroll-net">
                <small>Total value</small>
                <strong>{currencyExact(row.total_paycheck_value)}</strong>
                <em>{currencyExact(row.net_payment)} spendable</em>
              </span>
              <span className="row-chevron">›</span>
            </button>
          ))}
        </div>
      </section>
      </>}
      {selected && <PayrollDetail entry={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function PayrollDetail({ entry, onClose }: { entry: PayrollEntry; onClose: () => void }) {
  const values = [
    ["Gross", entry.gross_earnings],
    ["Taxes", entry.tax_withholdings],
    ["Spendable cash", entry.net_payment],
    ["Your account funding", entry.employee_account_funding],
    ["Employer additions", entry.employer_account_funding],
    ["Total paycheck value", entry.total_paycheck_value],
  ];
  const adjustments = Object.entries(entry.adjustments).filter(([, value]) => toCents(value) !== 0);
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer payroll-drawer" onClick={(event) => event.stopPropagation()} aria-label="Paycheck details">
        <button className="icon-button" onClick={onClose} aria-label="Close paycheck details">×</button>
        <span className={`payroll-source source-${entry.source_kind}`}>
          {entry.source_kind === "statement" ? "Statement" : "Calculated"}
        </span>
        <h2>{shortDate(entry.observed_deposit_date)} paycheck</h2>
        <p className="muted">{entry.job_title ?? entry.employer} · official {entry.payment_date}</p>
        <div className="payroll-detail-summary">
          {values.map(([label, value]) => (
            <div key={label}><span>{label}</span><strong>{currencyExact(value)}</strong></div>
          ))}
        </div>
        {adjustments.length > 0 && (
          <div className="detail-section">
            <h3>Calculated adjustments</h3>
            <div className="payroll-detail-lines">
              {adjustments.map(([label, value]) => (
                <div key={label}><span>{roleLabel(label)}</span><strong>{currencyExact(value)}</strong></div>
              ))}
            </div>
          </div>
        )}
        {entry.allocations.some((allocation) => allocation.section !== "net") && (
          <div className="detail-section">
            <h3>Where it went</h3>
            <div className="payroll-detail-lines">
              {entry.allocations
                .filter((allocation) => allocation.section !== "net" && allocation.section !== "compensation")
                .map((allocation) => (
                  <div key={`${allocation.section}-${allocation.category}`}>
                    <span>{allocation.label}<small>{allocation.source_kind === "statement" ? "Statement" : "Calculated"}</small></span>
                    <strong>{currencyExact(allocation.amount)}</strong>
                  </div>
                ))}
            </div>
          </div>
        )}
        <div className="detail-section">
          <h3>Deposited to</h3>
          <div className="payroll-detail-lines">
            {entry.deposit_splits.map((split, index) => (
              <div key={`${split.account}-${index}`}>
                <span>{split.account}</span>
                <strong>{currencyExact(split.amount)}</strong>
              </div>
            ))}
          </div>
        </div>
        {entry.plaid_transactions.length > 0 && (
          <p className="plaid-match">Matched to {entry.plaid_transactions.length} Plaid deposit{entry.plaid_transactions.length === 1 ? "" : "s"}.</p>
        )}
      </aside>
    </div>
  );
}
