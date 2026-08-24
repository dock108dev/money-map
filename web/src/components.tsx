import type { ReactNode } from "react";

import { currency, currencyExact } from "./format";
import type { Paycheck, ReviewIssue } from "./types";
import { EmptyState, StatusPill } from "./ui-primitives";

export { AccountsView, ActivityView } from "./accounts/AccountViews";
export { ConnectionsView } from "./connections/ConnectionsView";
export { IncomeView } from "./income/IncomeView";
export { OverviewView } from "./overview/OverviewView";
export { default as WealthView } from "./wealth/WealthView";

export function EvidenceDrawer({
  paycheck,
  onClose,
}: {
  paycheck: Paycheck;
  onClose: () => void;
}) {
  const values = [
    ["Gross earnings", paycheck.gross_earnings],
    ["Imputed non-cash", paycheck.imputed_earnings],
    ["Pretax deductions", paycheck.pretax_deductions],
    ["Tax withholdings", paycheck.tax_withholdings],
    ["After-tax deductions", paycheck.after_tax_deductions],
    ["Net payment", paycheck.net_payment],
  ];
  const sectionLabels: Record<string, string> = {
    earnings: "Earnings",
    imputed: "Imputed earnings",
    pretax: "Pretax deductions",
    taxes: "Tax withholdings",
    after_tax: "After-tax deductions",
    employer_benefit: "Employer-paid benefits",
    employer_tax: "Employer taxes",
    net_distribution: "Net pay distribution",
  };
  const detailGroups = paycheck.details.reduce<Record<string, Paycheck["details"]>>(
    (groups, line) => {
      groups[line.section] = [...(groups[line.section] ?? []), line];
      return groups;
    },
    {},
  );
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()} aria-label="Source evidence">
        <button className="icon-button" onClick={onClose} aria-label="Close evidence">
          ×
        </button>
        <span className="eyebrow">Source evidence</span>
        <h2>Paycheck {paycheck.payment_date}</h2>
        <p className="muted">
          {paycheck.job_title ?? paycheck.employer}
          {paycheck.observed_deposit_date &&
            ` · funds received ${paycheck.observed_deposit_date}`}
        </p>
        <p className="muted">
          {paycheck.source.filename} · parser {paycheck.source.parser_version}
        </p>
        <div className="formula-card">
          {values.map(([label, value], index) => (
            <div key={label}>
              <span>{index === 0 ? "" : index === values.length - 1 ? "=" : "−"}</span>
              <label>{label}</label>
              <strong>{currency(value)}</strong>
            </div>
          ))}
        </div>
        {Object.entries(detailGroups).map(([section, lines]) => (
          <div className="payroll-detail-group" key={section}>
            <h3>{sectionLabels[section] ?? section.replaceAll("_", " ")}</h3>
            <div className="payroll-detail-lines">
              {lines.map((line, index) => (
                <div key={`${line.category}-${line.label}-${index}`}>
                  <span>{line.label}</span>
                  <strong>{currency(line.amount)}</strong>
                  <small>YTD {currency(line.ytd_amount)}</small>
                </div>
              ))}
            </div>
          </div>
        ))}
        <h3>Field locations</h3>
        <div className="evidence-list">
          {paycheck.evidence.map((item, index) => (
            <div key={`${item.field}-${index}`}>
              <span>{item.label}</span>
              <small>{item.location} · {item.confidence} confidence</small>
            </div>
          ))}
        </div>
        <div className="hash">
          <span>SHA-256</span>
          <code>{paycheck.source.hash}</code>
        </div>
      </aside>
    </div>
  );
}

export function ReviewView({
  issues,
  busy = false,
  onUpdateData,
  onOpenAccounts,
}: {
  issues: ReviewIssue[];
  busy?: boolean;
  onUpdateData?: () => void;
  onOpenAccounts?: () => void;
}) {
  if (!issues.length)
    return (
      <EmptyState title="Nothing needs attention">
        Observed balances and posted activity agree. Timing-only differences and expected setup
        gaps are not treated as exceptions.
      </EmptyState>
    );
  return (
    <div className="view-stack">
      <section className="page-heading" data-copy-budget="utility-page-heading">
        <span className="eyebrow">Needs attention</span>
        <h1 data-prose>Review</h1>
        <p data-prose>Unexplained balance differences stay here until new data or source evidence resolves them.</p>
      </section>
      <div className="review-grid">
        {issues.map((issue) => {
          const steps = Array.isArray(issue.details.next_steps)
            ? issue.details.next_steps.filter((step): step is string => typeof step === "string")
            : [];
          const evidence = [
            ["Opening", issue.details.opening_balance],
            ["Posted activity", issue.details.accounted_activity],
            ["Expected close", issue.details.expected_closing_balance],
            ["Observed close", issue.details.closing_balance],
          ].filter((row): row is [string, string] => typeof row[1] === "string");
          return (
            <section className="review-card" key={issue.id}>
              <div className="review-count">!</div>
              <div className="review-body">
                <span className="eyebrow">{String(issue.details.account_name ?? issue.entity_type)}</span>
                <h3>{issue.rule.replaceAll("_", " ")}</h3>
                <p>{String(issue.details.message ?? "Evidence or reconciliation needs review.")}</p>
                {evidence.length > 0 && (
                  <dl className="review-evidence">
                    {evidence.map(([label, value]) => (
                      <div key={label}><dt>{label}</dt><dd>{currencyExact(value)}</dd></div>
                    ))}
                  </dl>
                )}
                <div className="review-cause">
                  <span>Unexplained difference</span>
                  <strong>{currencyExact(issue.residual)}</strong>
                  <small>{String(issue.details.likely_cause ?? "needs source evidence").replaceAll("_", " ")}</small>
                </div>
                {steps.length > 0 && (
                  <ol className="review-steps">
                    {steps.map((step) => <li key={step}>{step}</li>)}
                  </ol>
                )}
                <div className="review-actions">
                  {onUpdateData && (
                    <button type="button" className="secondary-button" disabled={busy} onClick={onUpdateData}>
                      {busy ? "Updating…" : "Update data"}
                    </button>
                  )}
                  {onOpenAccounts && (
                    <button type="button" className="secondary-button" onClick={onOpenAccounts}>Open accounts</button>
                  )}
                  <StatusPill status={issue.status} />
                </div>
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
