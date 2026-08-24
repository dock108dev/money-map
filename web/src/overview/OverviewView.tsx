import { useEffect, useState } from "react";

import { currency, currencyExact, monthLabel, shortDate } from "../format";
import type { AccountsDashboard, Overview, TimelineRow } from "../types";
import { ActivityRows, MetricCard, roleLabel } from "../ui-primitives";

export function OverviewView({
  overview,
  accounts,
  timeline,
  busy,
  onPeriodChange,
  onShowAccounts,
  onShowActivity,
  onShowIncome,
  onShowWealth,
}: {
  overview: Overview;
  accounts: AccountsDashboard;
  timeline: TimelineRow[];
  busy: boolean;
  onPeriodChange: (startDate: string, endDate: string) => void;
  onShowAccounts: () => void;
  onShowActivity: () => void;
  onShowIncome: () => void;
  onShowWealth: () => void;
}) {
  const baseline = overview.recurring_paycheck;
  const [startDate, setStartDate] = useState(overview.period.start);
  const [endDate, setEndDate] = useState(overview.period.end);
  useEffect(() => {
    setStartDate(overview.period.start);
    setEndDate(overview.period.end);
  }, [overview.period.start, overview.period.end]);

  return (
    <div className="view-stack account-first-view" data-retired-surface="overview">
      <section className="net-worth-hero" aria-labelledby="overview-title">
        <div className="net-worth-copy">
          <span>Money Map</span>
          <h1 id="overview-title" data-prose>Overview</h1>
          <small>Net worth</small>
          <strong>{currency(accounts.totals.net_worth)}</strong>
          {accounts.as_of && <small>As of {shortDate(accounts.as_of)}</small>}
        </div>
        <div className="worth-breakdown">
          <MetricCard label="Assets" value={currency(accounts.totals.assets)} />
          <MetricCard label="Debt" value={currency(accounts.totals.debts)} />
        </div>
      </section>
      <p className="print-only print-evidence-header" aria-hidden="true">Overview evidence · {accounts.as_of ? shortDate(accounts.as_of) : `${shortDate(overview.period.start)}–${shortDate(overview.period.end)}`}</p>

      <section className="period-toolbar" aria-label="Overview period">
        <div className="period-presets">
          {Object.entries(overview.period_presets).map(([key, range]) => (
            <button
              className={range.start === overview.period.start && range.end === overview.period.end ? "active" : ""}
              key={key}
              disabled={busy}
              onClick={() => onPeriodChange(range.start, range.end)}
            >
              {key === "trailing_12" ? "Last 12 months" : key === "current_year" ? "2026" : key === "previous_year" ? "2025" : "All"}
            </button>
          ))}
        </div>
        <details className="custom-range">
          <summary>Custom range</summary>
          <div className="period-dates">
            <label>From<input aria-label="Custom range start" type="date" value={startDate} onChange={(event) => setStartDate(event.currentTarget.value)} /></label>
            <label>Through<input aria-label="Custom range end" type="date" value={endDate} onChange={(event) => setEndDate(event.currentTarget.value)} /></label>
            <button disabled={busy || startDate > endDate} onClick={() => onPeriodChange(startDate, endDate)}>Apply</button>
          </div>
        </details>
      </section>

      <section className="overview-metrics">
        <MetricCard label="Cash" value={currency(accounts.totals.cash)} tone="green" />
        <MetricCard
          label="Investments"
          value={currency(accounts.totals.investments)}
          tone="ink"
        />
        <MetricCard
          label="Money in"
          value={currency(accounts.totals.money_in)}
          note={activityPeriod(accounts)}
        />
        <MetricCard
          label="Money out"
          value={currency(accounts.totals.money_out)}
          note={activityPeriod(accounts)}
          tone="warm"
        />
      </section>

      <section className="overview-links" aria-label="Money detail views">
        <button onClick={onShowIncome}><span>Income</span><strong>{overview.coverage.paychecks_in_period} paychecks</strong></button>
        <button onClick={onShowAccounts}><span>Accounts</span><strong>{accounts.accounts.length} connected</strong></button>
        <button onClick={onShowActivity}><span>Activity</span><strong>{Math.min(accounts.activity.length, 5)} recent</strong></button>
        <button onClick={onShowWealth}><span>Wealth</span><strong>Access and performance</strong></button>
      </section>

      <details className="panel overview-evidence evidence-disclosure">
        <summary>Detailed period evidence</summary>
        <div className="overview-evidence-stack">
          <section className="compact-panel income-snapshot">
            <header className="compact-heading"><div><h2>Income</h2><span>{overview.coverage.paychecks_in_period} paychecks</span></div></header>
            <div className="income-snapshot-metrics">
              <MetricCard label="Gross" value={currency(overview.totals.gross_compensation)} />
              <MetricCard label="Taxes" value={currency(overview.totals.taxes)} tone="warm" />
              <MetricCard label="Your account funding" value={currency(overview.totals.employee_directed_saving)} />
              <MetricCard label="Employer" value={currency(overview.totals.employer_contributions)} />
              <MetricCard label="Spendable net" value={currency(overview.totals.net_payments)} tone="green" />
            </div>
          </section>
          {baseline && <PaycheckAccountValue paycheck={baseline} />}
          <FidelityPeriodSnapshot overview={overview} accounts={accounts} />
          <PaycheckFlow overview={overview} />
          <section className="compact-panel"><header className="compact-heading"><div><h2>Month by month</h2><span>{timeline.length} months</span></div></header><TimelineRows rows={timeline} /></section>
          <section className="compact-panel"><header className="compact-heading"><div><h2>Recent activity</h2><span>Five most recent</span></div></header><ActivityRows rows={accounts.activity.slice(0, 5)} /></section>
          {baseline && <section className="paycheck-strip"><span>Every paycheck</span><strong>{currencyExact(baseline.all_account_value)} to your accounts</strong><small>{currencyExact(baseline.net_payment)} spendable cash · next {shortDate(baseline.next_expected_deposit)}</small></section>}
        </div>
      </details>
      <button className="secondary-button overview-print-button print-hidden" onClick={() => window.print()}>Print evidence</button>
    </div>
  );
}

function PaycheckAccountValue({
  paycheck,
}: {
  paycheck: NonNullable<Overview["recurring_paycheck"]>;
}) {
  const destinations = [
    { label: "Spendable cash", note: "SoFi net pay", value: paycheck.net_payment },
    {
      label: "Fidelity funded by you",
      note: "Retirement + stock plan",
      value: paycheck.employee_fidelity_funding,
    },
    { label: "HSA funded by you", note: "Pretax contribution", value: paycheck.employee_hsa },
    {
      label: "Employer Fidelity",
      note: "Retirement contribution",
      value: paycheck.employer_retirement,
    },
    { label: "Employer HSA", note: "Employer contribution", value: paycheck.employer_hsa },
  ];
  return (
    <section className="panel paycheck-value-panel">
      <div className="paycheck-value-hero">
        <div>
          <span className="eyebrow">Paycheck across your accounts</span>
          <strong>{currencyExact(paycheck.all_account_value)}</strong>
          <p>
            Net pay stays spendable cash. This total adds money deposited into accounts you own,
            plus employer contributions.
          </p>
        </div>
        <div className="paycheck-value-equation">
          <span>{currencyExact(paycheck.net_payment)} cash</span>
          <b>+</b>
          <span>{currencyExact(paycheck.employee_account_funding)} from you</span>
          <b>+</b>
          <span>{currencyExact(paycheck.employer_account_funding)} employer</span>
        </div>
      </div>
      <div className="paycheck-value-breakdown">
        {destinations.map((destination) => (
          <div className="account-value-row" key={destination.label}>
            <span>{destination.label}<small>{destination.note}</small></span>
            <strong>{currencyExact(destination.value)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function FidelityPeriodSnapshot({
  overview,
  accounts,
}: {
  overview: Overview;
  accounts: AccountsDashboard;
}) {
  const fidelityValueInCents = accounts.accounts
    .filter(
      (account) =>
        account.category === "investment" && account.institution.toLowerCase().includes("fidelity"),
    )
    .reduce((total, account) => total + Math.round(Number(account.current_balance ?? 0) * 100), 0);
  const fidelityValue = (fidelityValueInCents / 100).toFixed(2);
  const performanceAvailable =
    overview.investments.bridge_count > 0 && overview.investments.investment_result != null;
  return (
    <section className="panel fidelity-period-panel">
      <header className="compact-heading">
        <div>
          <h2>Fidelity over this period</h2>
          <span>{shortDate(overview.period.start)}–{shortDate(overview.period.end)}</span>
        </div>
        <strong>{currencyExact(fidelityValue)} now</strong>
      </header>
      <div className="fidelity-period-metrics">
        <MetricCard
          label="You contributed"
          value={currencyExact(overview.investments.employee_fidelity_contributions)}
          note="Retirement + stock plan"
        />
        <MetricCard
          label="Employer added"
          value={currencyExact(overview.investments.employer_contributions)}
          note="Retirement contribution"
        />
        <MetricCard
          label="Payroll funding"
          value={currencyExact(overview.investments.total_payroll_fidelity_contributions)}
          note="You + employer"
        />
        <MetricCard
          label="Investment result"
          value={performanceAvailable ? currencyExact(overview.investments.investment_result) : "Tracking"}
          note={performanceAvailable ? "For the selected period" : "Waiting for a clean comparison interval"}
          tone={performanceAvailable ? "green" : ""}
        />
      </div>
      <div className="fidelity-period-note">
        <p>
          Current value and payroll contributions are known. Performance stays in tracking until
          there is a longer, unambiguous opening-to-closing value interval; opening value matters,
          so current value minus contributions would not be a valid return.
        </p>
        <div>
          <span>Other investment deposits <strong>{currencyExact(overview.investments.other_contributions)}</strong></span>
          <span>External withdrawals <strong>{currencyExact(overview.investments.withdrawals)}</strong></span>
        </div>
      </div>
    </section>
  );
}

function PaycheckFlow({ overview }: { overview: Overview }) {
  const gross = Math.max(Number(overview.totals.gross_compensation ?? 0), 1);
  const destinations = overview.allocation.destinations
    .filter((row) => !["compensation", "employer"].includes(row.section))
    .sort((left, right) => Number(right.amount ?? 0) - Number(left.amount ?? 0));
  const employerAdditions = overview.allocation.destinations
    .filter((row) => row.section === "employer")
    .sort((left, right) => Number(right.amount ?? 0) - Number(left.amount ?? 0));
  const reconciliation = overview.allocation.reconciliation;
  return (
    <section className="panel money-flow-panel">
      <header className="compact-heading">
        <div><h2>Where gross pay went</h2><span>{overview.coverage.paychecks_in_period} paychecks</span></div>
        <strong>{currency(overview.totals.gross_compensation)}</strong>
      </header>
      <div className="money-flow">
        {destinations.map((row) => {
          const width = Math.max(1.5, (Number(row.amount ?? 0) / gross) * 100);
          return (
            <div className={`money-flow-row section-${row.section}`} key={`${row.section}-${row.category}-${row.label}`}>
              <span>{row.label}</span>
              <div><i style={{ width: `${Math.min(100, width)}%` }} /></div>
              <strong>{currency(row.amount)}</strong>
            </div>
          );
        })}
      </div>
      <div className={`gross-reconciliation reconciliation-${reconciliation.status}`}>
        <div>
          <strong>Gross pay accounted for</strong>
          <span>Taxes, deductions, net deposits, and non-cash taxable benefits</span>
        </div>
        <div>
          <strong>{currencyExact(reconciliation.accounted_from_gross)}</strong>
          <span>Difference {currencyExact(reconciliation.residual)}</span>
        </div>
      </div>
      {employerAdditions.length > 0 && (
        <div className="employer-additions">
          <div className="flow-subheading">
            <strong>Employer-paid additions</strong>
            <span>Additional money — not deducted from gross pay</span>
          </div>
          <div className="money-flow">
            {employerAdditions.map((row) => {
              const width = Math.max(1.5, (Number(row.amount ?? 0) / gross) * 100);
              return (
                <div className="money-flow-row section-employer" key={`${row.category}-${row.label}`}>
                  <span>{row.label}</span>
                  <div><i style={{ width: `${Math.min(100, width)}%` }} /></div>
                  <strong>{currency(row.amount)}</strong>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

function TimelineRows({ rows }: { rows: TimelineRow[] }) {
  if (!rows.length) return <div className="simple-empty">No activity in this period.</div>;
  const max = Math.max(...rows.map((row) => Number(row.gross_pay ?? 0)), 1);
  return (
    <div className="timeline-cards">
      {rows.map((row) => (
        <article key={row.month}>
          <div><strong>{monthLabel(row.month)}</strong><span>{currency(row.net_pay)} net pay</span></div>
          <div className="timeline-bar"><i style={{ width: `${(Number(row.gross_pay ?? 0) / max) * 100}%` }} /></div>
          <dl>
            <div><dt>Gross</dt><dd>{currency(row.gross_pay)}</dd></div>
            <div><dt>Cash out</dt><dd>{currency(row.cash_outflows)}</dd></div>
            <div><dt>Invested</dt><dd>{currency(row.investment_contributions)}</dd></div>
            <div><dt>Result</dt><dd>{currency(row.investment_result)}</dd></div>
          </dl>
        </article>
      ))}
    </div>
  );
}

const activityPeriod = (data: AccountsDashboard) => {
  if (!data.activity_period.start || !data.activity_period.end) return "Imported activity";
  return `${shortDate(data.activity_period.start)}–${shortDate(data.activity_period.end)}`;
};
