import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { addAccountValue, loadAccountDetail } from "./api";
import type {
  AccountDetail as AccountDetailData,
  AccountActivity,
  AccountsDashboard,
  ConnectedAccount,
  DashboardData,
  FidelitySummary,
  ForecastPeriod,
  Overview,
  Paycheck,
  PayrollEntry,
  PayrollHistory,
  PlaidStatus,
  ReviewIssue,
  Scenario,
  SofiSummary,
  TimelineRow,
  WealthDashboard,
} from "./types";

export { default as WealthView } from "./wealth/WealthView";

export const currency = (value: string | null | undefined) => {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Number(value));
};

export const currencyExact = (value: string | null | undefined) => {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
};

export const signedCurrencyExact = (value: string | null | undefined) => {
  if (value == null) return "—";
  const numeric = Number(value);
  return `${numeric > 0 ? "+" : ""}${currencyExact(value)}`;
};

export const monthLabel = (value: string) =>
  new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" }).format(
    new Date(value),
  );

export const shortDate = (value: string) =>
  new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(
    new Date(value),
  );

export function StatusPill({ status }: { status: string }) {
  return <span className={`status status-${status}`}>{status.replaceAll("_", " ")}</span>;
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">○</div>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}

function MetricCard({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: string;
}) {
  return (
    <article className={`metric-card ${tone ?? ""}`}>
      <span className="eyebrow">{label}</span>
      <strong>{value}</strong>
      {note && <small>{note}</small>}
    </article>
  );
}

export function WarningList({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return (
    <div className="notice" role="status">
      <span className="notice-mark">!</span>
      <div>
        <strong>Assumptions</strong>
        <ul>
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

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

const roleLabel = (role: string) =>
  role
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

function ActivityRows({ rows }: { rows: AccountActivity[] }) {
  if (!rows.length) return <div className="simple-empty">No activity yet.</div>;
  return (
    <div className="activity-list">
      {rows.map((row) => (
        <div className="activity-row" key={row.id}>
          <span className={`activity-icon direction-${row.direction}`}>
            {row.direction === "in" ? "↓" : row.direction === "out" ? "↑" : "↔"}
          </span>
          <span className="activity-main">
            <strong>{row.description}</strong>
            <small>{row.account} · {row.institution}</small>
          </span>
          <span className="activity-kind">{shortDate(row.date)} · {roleLabel(row.role)}</span>
          <strong className={`activity-amount direction-${row.direction}`}>
            {row.direction === "in" ? "+" : ""}{currencyExact(row.amount)}
          </strong>
        </div>
      ))}
    </div>
  );
}

const categoryLabel: Record<ConnectedAccount["category"], string> = {
  cash: "Cash",
  investment: "Investments",
  debt: "Debt",
  other: "Other",
};

export function AccountsView({ data }: { data: AccountsDashboard }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = data.accounts.find((account) => account.id === selectedId) ?? null;
  const [detail, setDetail] = useState<AccountDetailData | null>(null);
  const [detailError, setDetailError] = useState("");
  const [detailBusy, setDetailBusy] = useState(false);
  const periodStart = data.activity_period.start ?? "2025-01-01";
  const periodEnd = data.as_of ?? data.activity_period.end ?? "2026-07-29";
  const categories = (["cash", "investment", "debt", "other"] as const).filter((category) =>
    data.accounts.some((account) => account.category === category),
  );

  const refreshDetail = async (accountId: number) => {
    setDetailBusy(true);
    setDetailError("");
    try {
      setDetail(await loadAccountDetail(accountId, periodStart, periodEnd));
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "Account details could not load.");
    } finally {
      setDetailBusy(false);
    }
  };

  useEffect(() => {
    if (selectedId == null) {
      setDetail(null);
      return;
    }
    void refreshDetail(selectedId);
  }, [selectedId, periodStart, periodEnd]);

  return (
    <div className="view-stack account-first-view">
      <section className="simple-page-heading" data-copy-budget="utility-page-heading">
        <div>
          <span className="eyebrow">{data.accounts.length} accounts</span>
          <h1 data-prose>Accounts</h1>
        </div>
        <strong>{currency(data.totals.net_worth)} net worth</strong>
      </section>
      <div className="account-groups">
        {categories.map((category) => {
          const rows = data.accounts.filter((account) => account.category === category);
          const total = rows.reduce((sum, account) => sum + Number(account.current_balance ?? 0), 0);
          return (
            <section className="panel compact-panel" key={category}>
              <header className="compact-heading">
                <div>
                  <h2>{categoryLabel[category]}</h2>
                  <span>{rows.length} account{rows.length === 1 ? "" : "s"}</span>
                </div>
                <strong>{currency(String(total))}</strong>
              </header>
              <div className="account-list">
                {rows.map((account) => (
                  <button
                    className={selectedId === account.id ? "account-list-row selected" : "account-list-row"}
                    key={account.id}
                    onClick={() => setSelectedId(account.id)}
                  >
                    <span className={`account-avatar category-${account.category}`}>
                      {account.institution.slice(0, 1)}
                    </span>
                    <span>
                      <strong>{account.name}</strong>
                      <small>{account.institution} · {account.type}</small>
                    </span>
                    <span className="account-meta">
                      <strong>{currency(account.current_balance)}</strong>
                      {account.balance_as_of && <small>{shortDate(account.balance_as_of)}</small>}
                    </span>
                    <span className="row-chevron">›</span>
                  </button>
                ))}
              </div>
            </section>
          );
        })}
      </div>
      {data.accounts.length === 0 && (
        <div className="simple-empty" role="status">No accounts are connected. Add an account to build this view.</div>
      )}
      {detailBusy && <div className="simple-empty">Loading account…</div>}
      {detailError && <div className="error-banner">{detailError}</div>}
      {selected && detail && (
        <AccountDetailPanel
          account={selected}
          detail={detail}
          onValueAdded={() => void refreshDetail(selected.id)}
        />
      )}
    </div>
  );
}

function AccountDetailPanel({
  account,
  detail,
  onValueAdded,
}: {
  account: ConnectedAccount;
  detail: AccountDetailData;
  onValueAdded: () => void;
}) {
  const [addingValue, setAddingValue] = useState(false);
  const [valueMessage, setValueMessage] = useState("");
  const submitValue = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAddingValue(true);
    const form = new FormData(event.currentTarget);
    try {
      await addAccountValue(account.id, {
        observation_date: String(form.get("observation_date")),
        value: String(form.get("value")),
        source_note: String(form.get("source_note")),
      });
      setValueMessage("Starting value saved.");
      onValueAdded();
    } catch (reason) {
      setValueMessage(reason instanceof Error ? reason.message : "Value could not be saved.");
    } finally {
      setAddingValue(false);
    }
  };
  return (
    <section className="panel account-detail" aria-label={`${account.name} details`}>
      <header className="account-detail-heading">
        <div>
          <span className="eyebrow">{account.institution}</span>
          <h2>{account.name}</h2>
          <small>{account.type} · {account.source}</small>
        </div>
        <div>
          <strong>{currency(account.current_balance)}</strong>
          {account.balance_as_of && <small>As of {shortDate(account.balance_as_of)}</small>}
        </div>
      </header>
      <div className="detail-metrics">
        {account.category === "cash" && (
          <>
            <MetricCard label="Money in" value={currency(account.inflows)} />
            <MetricCard label="Money out" value={currency(account.outflows)} />
          </>
        )}
        {account.category === "investment" && (
          <>
            <MetricCard label="Deposits" value={currency(account.contributions)} />
            <MetricCard label="Unrealized gain" value={currency(detail.unrealized_gain)} />
            <MetricCard
              label="Performance"
              value={
                account.performance_status === "available"
                  ? currency(account.investment_result)
                  : "Tracking"
              }
            />
          </>
        )}
        {account.change != null && <MetricCard label="Balance change" value={currency(account.change)} />}
        <MetricCard
          label={account.holding_count ? "Holdings" : "Transactions"}
          value={String(account.holding_count || account.transaction_count)}
        />
      </div>
      {detail.balance_points.length > 0 && (
        <div className="detail-section">
          <h3>Balance history</h3>
          <div className="balance-history">
            {detail.balance_points.map((point) => (
              <div key={`${point.date}-${point.kind}`}>
                <span>{shortDate(point.date)}</span>
                <strong>{currency(point.amount)}</strong>
                <small>{point.source_kind === "observed" ? "Observed" : "Calculated"}</small>
              </div>
            ))}
          </div>
        </div>
      )}
      {detail.bridges.length > 0 && (
        <div className="detail-section">
          <h3>Investment performance</h3>
          {detail.bridges.map((bridge) => (
            <div className="bridge-summary" key={`${String(bridge.period_start)}-${String(bridge.period_end)}`}>
              <div><span>Opening</span><strong>{currency(bridge.opening_value as string | null)}</strong></div>
              <div><span>Contributions</span><strong>{currency(String(
                Number(bridge.employee_contributions ?? 0) +
                Number(bridge.employer_contributions ?? 0) +
                Number(bridge.stock_plan_contributions ?? 0) +
                Number(bridge.other_deposits ?? 0)
              ))}</strong></div>
              <div><span>Withdrawals</span><strong>{currency(bridge.withdrawals as string | null)}</strong></div>
              <div>
                <span>Investment result</span>
                <strong>
                  {bridge.performance_status === "available"
                    ? currency(bridge.investment_result as string | null)
                    : "Tracking"}
                </strong>
              </div>
              <div><span>Closing</span><strong>{currency(bridge.closing_value as string | null)}</strong></div>
              <small>
                {String(bridge.performance_message ?? bridge.return_method)}
                {bridge.calculated_return_pct ? ` · ${bridge.calculated_return_pct}%` : ""}
              </small>
            </div>
          ))}
        </div>
      )}
      {account.category === "investment" && detail.performance_status === "tracking" && (
        <form className="inline-value-form" onSubmit={(event) => void submitValue(event)}>
          <strong>Add an earlier account value</strong>
          <input name="observation_date" type="date" max={detail.balance_as_of ?? undefined} required />
          <input name="value" type="number" min="0" step="0.01" placeholder="Market value" required />
          <input name="source_note" defaultValue="Fidelity statement" maxLength={200} required />
          <button className="secondary-button" disabled={addingValue}>{addingValue ? "Saving…" : "Save value"}</button>
          {valueMessage && <small>{valueMessage}</small>}
        </form>
      )}
      {account.holdings.length > 0 && (
        <div className="detail-section">
          <h3>Holdings</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Holding</th><th>Ticker</th><th>Quantity</th><th>Value</th></tr></thead>
              <tbody>
                {account.holdings.map((holding, index) => (
                  <tr key={`${holding.ticker ?? holding.name}-${index}`}>
                    <td>{holding.name}</td>
                    <td>{holding.ticker ?? "—"}</td>
                    <td>{Number(holding.quantity).toLocaleString()}</td>
                    <td>{currency(holding.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {detail.monthly.length > 0 && account.category === "cash" && (
        <div className="detail-section">
          <h3>Monthly cash flow</h3>
          <div className="table-wrap"><table>
            <thead><tr><th>Month</th><th>Opening</th><th>In</th><th>Out</th><th>Closing</th></tr></thead>
            <tbody>{detail.monthly.map((row) => (
              <tr key={row.month}><td>{monthLabel(row.month)}</td><td>{currency(row.opening)}</td><td>{currency(row.inflows)}</td><td>{currency(row.outflows)}</td><td>{currency(row.closing)}</td></tr>
            ))}</tbody>
          </table></div>
        </div>
      )}
      {detail.activity.length > 0 && (
        <div className="detail-section">
          <h3>Activity</h3>
          <div className="activity-list">
            {detail.activity.slice(0, 30).map((row) => (
              <div className="activity-row" key={row.id}>
                <span className={`activity-icon direction-${Number(row.amount ?? 0) >= 0 ? "in" : "out"}`}>{Number(row.amount ?? 0) >= 0 ? "↓" : "↑"}</span>
                <span className="activity-main"><strong>{row.description}</strong><small>{shortDate(row.date)} · {roleLabel(row.role)}</small></span>
                <strong className={`activity-amount direction-${Number(row.amount ?? 0) >= 0 ? "in" : "out"}`}>{currencyExact(row.amount)}</strong>
              </div>
            ))}
          </div>
        </div>
      )}
      <footer className="source-line">
        {account.source}{account.last_synced_at ? ` · synced ${new Date(account.last_synced_at).toLocaleString()}` : ""}
      </footer>
    </section>
  );
}

type ActivityFilter = "all" | "in" | "out" | "transfer" | "investment";

export function ActivityView({
  data,
  period = null,
}: {
  data: AccountsDashboard;
  period?: { startDate: string; endDate: string } | null;
}) {
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const periodRows = period
    ? data.activity.filter((row) => row.date >= period.startDate && row.date <= period.endDate)
    : data.activity;
  const rows = periodRows.filter((row) => {
    if (filter === "all") return true;
    if (filter === "investment") return row.account_category === "investment";
    return row.direction === filter;
  });
  return (
    <div className="view-stack account-first-view">
      <section className="simple-page-heading" data-copy-budget="utility-page-heading">
        <div>
          <span className="eyebrow">
            {period
              ? `${shortDate(period.startDate)}–${shortDate(period.endDate)} · inclusive`
              : activityPeriod(data)}
          </span>
          <h1 data-prose>Activity</h1>
        </div>
        <strong>{rows.length} records</strong>
      </section>
      <div className="filter-bar" role="group" aria-label="Activity filters">
        {(["all", "in", "out", "transfer", "investment"] as const).map((item) => (
          <button className={filter === item ? "active" : ""} key={item} onClick={() => setFilter(item)}>
            {item === "all" ? "All" : item === "in" ? "Money in" : item === "out" ? "Money out" : roleLabel(item)}
          </button>
        ))}
      </div>
      <section className="panel compact-panel">
        <ActivityRows rows={rows} />
      </section>
    </div>
  );
}

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

  return (
    <div className="view-stack account-first-view">
      <section className="simple-page-heading income-heading" data-copy-budget="utility-page-heading">
        <div>
          <span className="eyebrow">Every other Wednesday</span>
          <h1 data-prose>Income</h1>
        </div>
        <strong>{rows.length} paychecks</strong>
      </section>
      <div className="date-range" aria-label="Income date range">
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
      </div>
      <section className="overview-metrics income-metrics">
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

export function TimelineView({ rows }: { rows: TimelineRow[] }) {
  return (
    <div className="view-stack">
      <section className="page-heading">
        <span className="eyebrow">Monthly timeline</span>
        <h1>History, month by month.</h1>
        <p>Completed payroll and connected account activity in one view.</p>
      </section>
      <section className="panel">
        {rows.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Month</th><th>Gross</th><th>Taxes</th><th>Net pay</th>
                  <th>Investment deposits</th><th>Investment result</th><th>Cash in</th><th>Cash out</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.month}>
                    <td>{monthLabel(row.month)}</td>
                    <td>{currency(row.gross_pay)}</td>
                    <td>{currency(row.taxes)}</td>
                    <td>{currency(row.net_pay)}</td>
                    <td>{currency(row.investment_contributions)}</td>
                    <td>{currency(row.investment_result)}</td>
                    <td>{currency(row.cash_inflows)}</td>
                    <td>{currency(row.cash_outflows)}</td>
                    <td><StatusPill status={row.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="No history yet">Import payroll or account records to build the timeline.</EmptyState>
        )}
      </section>
    </div>
  );
}

function BridgeEquation({ bridge }: { bridge: Record<string, string | null> }) {
  const rows = [
    ["Opening value", bridge.opening_value, "+"],
    ["Employee contributions", bridge.employee_contributions, "+"],
    ["Employer contributions", bridge.employer_contributions, "+"],
    ["Stock-plan deposits", bridge.stock_plan_contributions, "+"],
    ["Other deposits", bridge.other_deposits, "+"],
    ["Withdrawals", bridge.withdrawals, "−"],
    ["Investment result", bridge.investment_result, "+"],
    ["Closing value", bridge.closing_value, "="],
  ];
  return (
    <div className="bridge-equation">
      {rows.map(([label, value, sign]) => (
        <div key={label}><span>{sign}</span><label>{label}</label><strong>{currency(value)}</strong></div>
      ))}
    </div>
  );
}

export function FidelityView({ data }: { data: FidelitySummary }) {
  return (
    <div className="view-stack">
      <section className="page-heading">
        <span className="eyebrow">Fidelity bridge</span>
        <h1>Deposits are not investment returns.</h1>
        <p>External contributions and market results are reconciled separately.</p>
      </section>
      {data.accounts.length > 0 && <WarningList warnings={data.warnings} />}
      {data.accounts.length ? (
        <>
          {Object.keys(data.consolidated).length > 0 && (
            <section className="panel"><BridgeEquation bridge={data.consolidated} /></section>
          )}
          {data.accounts.map((account) => (
            <section className="panel" key={String(account.account)}>
              <header className="section-heading">
                <div>
                  <span className="eyebrow">{String(account.source ?? "Evidence")}</span>
                  <h2>{String(account.account)}</h2>
                </div>
                <div className="current-value">
                  <small>Current value</small>
                  <strong>{currency(account.current_value as string | null)}</strong>
                </div>
              </header>
              {account.opening_value != null ? (
                <BridgeEquation bridge={account as Record<string, string | null>} />
              ) : (
                <p className="pending-bridge">
                  The current value is factual. Investment result remains unresolved until a
                  second dated value is synchronized.
                </p>
              )}
              {Array.isArray(account.holdings) && account.holdings.length > 0 && (
                <div className="table-wrap holdings-table">
                  <table>
                    <thead>
                      <tr><th>Holding</th><th>Ticker</th><th>Quantity</th><th>Value</th><th>As of</th></tr>
                    </thead>
                    <tbody>
                      {(account.holdings as Array<Record<string, unknown>>).map((holding, index) => (
                        <tr key={`${String(holding.name)}-${index}`}>
                          <td>{String(holding.name)}</td>
                          <td>{String(holding.ticker ?? "—")}</td>
                          <td>{Number(holding.quantity).toLocaleString()}</td>
                          <td>{currency(holding.value as string | null)}</td>
                          <td>{String(holding.as_of)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          ))}
        </>
      ) : (
        <EmptyState title="Fidelity evidence is still needed">
          Connect Fidelity to load balances, holdings, contributions, and investment results.
        </EmptyState>
      )}
    </div>
  );
}

export function SofiView({ data }: { data: SofiSummary }) {
  return (
    <div className="view-stack">
      <section className="page-heading">
        <span className="eyebrow">SoFi flow</span>
        <h1>Checking and savings, without spending categories.</h1>
        <p>Axos and Provident source labels normalize to SoFi; internal transfers cancel when consolidated.</p>
      </section>
      {data.accounts.length > 0 && <WarningList warnings={data.warnings} />}
      {data.accounts.length ? (
        <section className="account-grid">
          {data.accounts.map((account) => (
            <article className="panel account-card" key={String(account.id)}>
              <span className="eyebrow">{String(account.type)}</span>
              <h2>{String(account.name)}</h2>
              <MetricCard label="Opening" value={currency(account.opening_balance as string | null)} />
              <MetricCard label="Inflows" value={currency(account.inflows as string | null)} />
              <MetricCard label="Outflows" value={currency(account.outflows as string | null)} />
              <MetricCard label="Closing" value={currency(account.closing_balance as string | null)} />
            </article>
          ))}
        </section>
      ) : (
        <EmptyState title="SoFi is not connected yet">
          Connect SoFi to load balances and transactions.
        </EmptyState>
      )}
    </div>
  );
}

export function ConnectionsView({
  plaid,
  busy,
  message,
  onConfigure,
  onConnect,
  onSync,
  onRepair,
  onDisconnect,
  imports,
  onImport,
  onReport,
  onAutoRefreshChange,
}: {
  plaid: PlaidStatus;
  busy: boolean;
  message: string;
  onConfigure: (payload: {
    environment: "sandbox" | "production";
  }) => void;
  onConnect: (
    target: "sofi" | "fidelity",
    environment: "sandbox" | "production",
  ) => void;
  onSync: (connectionId: number) => void;
  onRepair: (connectionId: number) => void;
  onDisconnect: (connectionId: number) => void;
  imports: DashboardData["imports"];
  onImport: () => void;
  onReport: () => void;
  onAutoRefreshChange: (enabled: boolean) => void;
}) {
  const [showOlderImports, setShowOlderImports] = useState(false);
  const liveReady = plaid.configuration.production.configured;

  return (
    <div className="view-stack account-first-view">
      <section className="simple-page-heading" data-copy-budget="utility-page-heading">
        <div>
          <span className="eyebrow">Plaid</span>
          <h1 data-prose>Add account</h1>
        </div>
        <strong>{plaid.connections.length} connected</strong>
      </section>
      {message && <div className="action-message connection-message">{message}</div>}
      <label className="refresh-preference panel compact-panel">
        <span>
          <strong>Update automatically when Money Map opens</strong>
          <small>At most once each day</small>
        </span>
        <input
          type="checkbox"
          checked={plaid.refresh.auto_refresh_enabled}
          disabled={busy}
          onChange={(event) => onAutoRefreshChange(event.currentTarget.checked)}
        />
      </label>
      <section className="add-account-grid">
        <button className="add-account-card" disabled={busy || !liveReady} onClick={() => onConnect("sofi", "production")}>
          <span className="add-account-icon">＋</span>
          <span><strong>Bank, credit or loan</strong><small>Balances and transactions</small></span>
        </button>
        <button className="add-account-card" disabled={busy || !liveReady} onClick={() => onConnect("fidelity", "production")}>
          <span className="add-account-icon">＋</span>
          <span><strong>Investment account</strong><small>Balances, holdings and activity</small></span>
        </button>
        <button className="add-account-card" disabled={busy} onClick={onImport}>
          <span className="add-account-icon">⇩</span>
          <span><strong>Import files</strong><small>Private inbox</small></span>
        </button>
        <button className="add-account-card" disabled={busy} onClick={onReport}>
          <span className="add-account-icon">▧</span>
          <span><strong>Create report</strong><small>Saved locally</small></span>
        </button>
      </section>
      {plaid.connections.length > 0 && (
        <section className="panel compact-panel">
          <header className="compact-heading"><div><h2>Connections</h2><span>Read-only</span></div></header>
          <div className="connection-list">
            {plaid.connections.map((connection) => (
              <div className="connection-row" key={connection.id}>
                <span className="connection-avatar">{connection.institution_name.slice(0, 1)}</span>
                <div>
                  <strong>{connection.institution_name}</strong>
                  <small>
                    {connection.account_count} account{connection.account_count === 1 ? "" : "s"} · {connection.last_synced_at ? `synced ${new Date(connection.last_synced_at).toLocaleString()}` : "not synced"}
                  </small>
                  {connection.last_error && <em>{connection.last_error}</em>}
                </div>
                <StatusPill status={connection.status} />
                <div className="row-actions">
                  <button className="secondary-button" disabled={busy} onClick={() => onSync(connection.id)}>Update</button>
                  {connection.status === "needs_attention" && (
                    <button className="secondary-button" disabled={busy} onClick={() => onRepair(connection.id)}>Reconnect</button>
                  )}
                  <button
                    className="plain-danger-button"
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm("Remove this connection and its local account data?")) {
                        onDisconnect(connection.id);
                      }
                    }}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
      {imports.length > 0 && (
        <section className="panel compact-panel">
          <header className="compact-heading"><div><h2>Recent imports</h2><span>{imports.length} batches</span></div></header>
          <div className="import-history-compact" data-default-visible-count="5">
            {imports.slice(0, showOlderImports ? imports.length : 5).map((batch) => (
              <div key={batch.id}><span>Batch {batch.id}</span><strong>{batch.imported} imported</strong><small>{batch.duplicates} already current</small></div>
            ))}
          </div>
          {!showOlderImports && imports.length > 5 && <button className="secondary-button show-older-button" onClick={() => setShowOlderImports(true)}>Show older evidence</button>}
        </section>
      )}
      {!liveReady && (
        <section className="panel plaid-setup" id="plaid-live-setup">
          <div>
            <span className="eyebrow">Plaid setup</span>
            <h2>Set up production access</h2>
            <p>Your credentials are entered in a private macOS prompt, not this page.</p>
            <a
              className="secondary-button dashboard-link"
              href="https://dashboard.plaid.com/"
              target="_blank"
              rel="noreferrer"
            >
              Plaid Dashboard
            </a>
          </div>
          <button
            className="primary-button"
            disabled={busy}
            onClick={() => onConfigure({ environment: "production" })}
          >
            {busy ? "Opening…" : "Enter credentials"}
          </button>
        </section>
      )}
    </div>
  );
}

export function WealthReportView({ data }: { data: WealthDashboard }) {
  const [periodKey, setPeriodKey] = useState("observed");
  const selectedPeriod =
    data.fidelity.performance_periods.find((period) => period.key === periodKey) ??
    data.fidelity.performance_periods[0];
  const historyValues = data.fidelity.history.map((point) => Number(point.value ?? 0));
  const historyMin = historyValues.length ? Math.min(...historyValues) : 0;
  const historyMax = historyValues.length ? Math.max(...historyValues) : 1;
  const historyRange = Math.max(historyMax - historyMin, 1);
  const visibleFidelityAccounts = data.fidelity.accounts.filter(
    (account) => Number(account.current_value ?? 0) !== 0,
  );
  const observation = data.fidelity.recent_observation;

  return (
    <div className="view-stack account-first-view wealth-view">
      <section className="simple-page-heading wealth-heading">
        <div>
          <span className="eyebrow">Money you can use and investments you can measure</span>
          <h1>Wealth</h1>
        </div>
        {data.as_of && <strong>As of {shortDate(data.as_of)}</strong>}
      </section>

      <section className="wealth-access-hero">
        <div className="wealth-access-total">
          <span>Accessible wealth</span>
          <strong>{currencyExact(data.accessible.total)}</strong>
          <p>Cash and investments you confirmed are currently available to use or sell.</p>
        </div>
        <div className="wealth-access-breakdown">
          <MetricCard label="Cash" value={currencyExact(data.accessible.cash)} tone="green" />
          <MetricCard
            label="Sellable investments"
            value={currencyExact(data.accessible.sellable_investments)}
            tone="ink"
          />
          <MetricCard
            label="Tracked, not accessible"
            value={currencyExact(data.excluded.total)}
            note="Retirement + restricted equity"
          />
        </div>
      </section>

      {data.paycheck && (
        <section className="panel wealth-paycheck-panel">
          <header className="compact-heading">
            <div>
              <h2>What one paycheck can build</h2>
              <span>Before ordinary spending</span>
            </div>
            <strong>{currencyExact(data.paycheck.accessible_value_before_spending)} accessible</strong>
          </header>
          <div className="wealth-paycheck-grid">
            <MetricCard label="Spendable cash" value={currencyExact(data.paycheck.spendable_cash)} />
            <MetricCard label="Sellable stock funding" value={currencyExact(data.paycheck.accessible_stock_funding)} />
            <MetricCard label="Locked funding" value={currencyExact(data.paycheck.locked_account_funding)} note="401(k), HSA + employer" />
            <MetricCard label="Total paycheck value" value={currencyExact(data.paycheck.total_paycheck_value)} tone="green" />
          </div>
        </section>
      )}

      <section className="panel fidelity-performance-panel">
        <header className="fidelity-performance-heading">
          <div>
            <span className="eyebrow">All Fidelity accounts</span>
            <h2>{currencyExact(data.fidelity.current_value)}</h2>
            <p>Performance includes every Fidelity account; accessibility only affects the wealth headline.</p>
          </div>
          <div className="performance-funding-summary">
            <span>Last 12 months payroll funding</span>
            <strong>{currencyExact(data.fidelity.funding.total_payroll_funding)}</strong>
            <small>
              {currencyExact(data.fidelity.funding.you_contributed)} you · {currencyExact(data.fidelity.funding.employer_contributed)} employer
            </small>
          </div>
        </header>

        <div className="performance-period-tabs" role="group" aria-label="Fidelity performance period">
          {data.fidelity.performance_periods.map((period) => (
            <button
              className={period.key === selectedPeriod?.key ? "active" : ""}
              key={period.key}
              onClick={() => setPeriodKey(period.key)}
            >
              {period.label}
            </button>
          ))}
        </div>

        {selectedPeriod && (
          <div className={`performance-result performance-${selectedPeriod.status}`}>
            <div className="performance-result-primary">
              <span>{selectedPeriod.status === "available" ? "Investment result" : "Performance status"}</span>
              <strong>
                {selectedPeriod.status === "available"
                  ? signedCurrencyExact(selectedPeriod.investment_result)
                  : "Tracking"}
              </strong>
              <small>
                {selectedPeriod.status === "available" && selectedPeriod.return_pct
                  ? `${Number(selectedPeriod.return_pct).toFixed(2)}% after contributions`
                  : selectedPeriod.message}
              </small>
            </div>
            <div className="performance-equation">
              <div><span>Opening</span><strong>{currencyExact(selectedPeriod.opening_value)}</strong></div>
              <b>+</b>
              <div><span>Deposits</span><strong>{currencyExact(selectedPeriod.deposits)}</strong></div>
              <b>−</b>
              <div><span>Withdrawals</span><strong>{currencyExact(selectedPeriod.withdrawals)}</strong></div>
              <b>+</b>
              <div><span>Market result</span><strong>{selectedPeriod.investment_result ? signedCurrencyExact(selectedPeriod.investment_result) : "Tracking"}</strong></div>
              <b>=</b>
              <div><span>Current</span><strong>{currencyExact(selectedPeriod.closing_value)}</strong></div>
            </div>
          </div>
        )}

        <div className="fidelity-observation-grid">
          <div className="recent-observation-card">
            <span className="eyebrow">Latest observed movement</span>
            {observation ? (
              <>
                <strong>{signedCurrencyExact(observation.change)}</strong>
                <small>
                  {Number(observation.change_pct ?? 0).toFixed(2)}% · {shortDate(observation.period_start)}–{shortDate(observation.period_end)}
                </small>
                <p>{observation.message}</p>
              </>
            ) : (
              <p>A second synchronized value is needed.</p>
            )}
          </div>
          <div className="fidelity-history-card">
            <span className="eyebrow">Observed Fidelity value</span>
            <div className="wealth-history-chart" aria-label="Observed Fidelity value history">
              {data.fidelity.history.map((point) => {
                const height = 22 + ((Number(point.value ?? 0) - historyMin) / historyRange) * 78;
                return (
                  <div key={point.date}>
                    <i style={{ height: `${height}%` }} />
                    <small>{shortDate(point.date)}</small>
                  </div>
                );
              })}
            </div>
            <p>Balance movement is shown immediately. Contribution-adjusted performance unlocks only after a clean interval.</p>
          </div>
        </div>
      </section>

      <section className="panel compact-panel">
        <header className="compact-heading">
          <div>
            <h2>Fidelity accounts</h2>
            <span>Accessible, retirement and restricted accounts stay distinct</span>
          </div>
          <strong>{visibleFidelityAccounts.length} funded</strong>
        </header>
        <div className="wealth-account-list">
          {visibleFidelityAccounts.map((account) => (
            <div className="wealth-account-row" key={account.id}>
              <span className={`wealth-access-dot access-${account.access_status}`} />
              <span className="wealth-account-name">
                <strong>{account.name}</strong>
                <small>{roleLabel(account.type)} · {account.access_reason}</small>
              </span>
              <span className={`wealth-access-badge access-${account.access_status}`}>
                {account.access_status === "accessible" ? "Accessible" : account.access_status === "restricted" ? "Restricted" : account.access_status === "retirement" ? "Retirement" : roleLabel(account.access_status)}
              </span>
              <span className="wealth-account-movement">
                <small>After contributions</small>
                <strong>
                  {account.performance_status === "available"
                    ? signedCurrencyExact(account.investment_result)
                    : "Tracking"}
                </strong>
                <em>Recent {signedCurrencyExact(account.recent_change)}</em>
              </span>
              <strong className="wealth-account-value">{currencyExact(account.current_value)}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="wealth-method-note">
        <strong>No performance score yet—and no home value.</strong>
        <p>
          Money Map removes deposits and withdrawals before calculating investment gain or loss.
          Short observations stay factual rather than being annualized into a misleading rate.
        </p>
      </section>
    </div>
  );
}

export function ForecastChart({ periods }: { periods: ForecastPeriod[] }) {
  const max = Math.max(...periods.map((period) => Math.abs(Number(period.ending_cash ?? 0))), 1);
  return (
    <div className="forecast-chart" aria-label="Projected ending cash by month">
      {periods.map((period) => (
        <div className="forecast-column" key={period.month}>
          <span
            className={Number(period.ending_cash ?? 0) < 0 ? "negative" : undefined}
            style={{ height: `${Math.max(2, (Math.abs(Number(period.ending_cash ?? 0)) / max) * 100)}%` }}
          />
          <small>{monthLabel(period.month).split(" ")[0]}</small>
        </div>
      ))}
    </div>
  );
}

export function ForecastView({
  scenarios,
  onSubmit,
  busy,
}: {
  scenarios: Scenario[];
  onSubmit: (payload: Record<string, string | number | null>) => void;
  busy: boolean;
}) {
  const baseline = scenarios.find((scenario) => scenario.is_baseline) ?? scenarios[0];
  const baselineWarnings = Array.isArray(baseline?.inputs.assumption_warnings)
    ? baseline.inputs.assumption_warnings.filter(
        (warning): warning is string => typeof warning === "string",
      )
    : [];
  const observedOutflow = String(baseline?.inputs.monthly_outflow_effective ?? "0");
  const checkingSplit = Number(baseline?.inputs.checking_split_pct_effective ?? 100);
  return (
    <div className="view-stack account-first-view">
      <section className="simple-page-heading">
        <div><span className="eyebrow">Next 12 months</span><h1>Plan</h1></div>
        <strong>{scenarios.length} scenario{scenarios.length === 1 ? "" : "s"}</strong>
      </section>
      {baseline && (
        <section className="panel forecast-summary">
          <div>
            <span className="eyebrow">Current observed setup</span>
            <h2>{currency(baseline.periods.at(-1)?.ending_cash)} projected cash</h2>
            <p>{currency(baseline.periods.reduce((sum, row) => sum + Number(row.employee_retirement ?? 0), 0).toString())} employee retirement contributions</p>
            <dl className="forecast-evidence">
              <div><dt>Monthly outflow</dt><dd>{currency(observedOutflow)}</dd></div>
              <div><dt>Net deposit split</dt><dd>{checkingSplit.toFixed(2)}% checking · {(100 - checkingSplit).toFixed(2)}% savings</dd></div>
            </dl>
          </div>
          <ForecastChart periods={baseline.periods} />
        </section>
      )}
      <WarningList warnings={baselineWarnings} />
      <section className="scenario-layout">
        <form
          className="panel scenario-form"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            const payload = Object.fromEntries(data.entries()) as Record<string, string>;
            if (payload.bonus_month) payload.bonus_month = `${payload.bonus_month}-01`;
            else delete payload.bonus_month;
            onSubmit(payload);
          }}
        >
          <span className="eyebrow">Alternative scenario</span>
          <h2>Compare a change</h2>
          <label>Name<input name="name" defaultValue="Increase retirement" required /></label>
          <div className="field-row">
            <label>Additional 401(k) %<input name="additional_401k_pct" type="number" min="0" max="100" step="0.1" defaultValue="2" /></label>
            <label>Additional stock plan %<input name="stock_plan_pct" type="number" min="0" max="100" step="0.1" defaultValue="0" /></label>
          </div>
          <label>HSA each paycheck<input name="hsa_per_paycheck" type="number" min="0" step="0.01" placeholder="Use current" /></label>
          <label>Checking share of net SoFi deposit %<input name="checking_split_pct" type="number" min="0" max="100" step="0.01" placeholder={`Use observed ${checkingSplit.toFixed(2)}%`} /></label>
          <div className="field-row">
            <label>Monthly aggregate outflow<input name="monthly_outflow" type="number" min="0" step="0.01" placeholder={`Use observed ${currency(observedOutflow)}`} /></label>
            <label>Minimum cash floor<input name="cash_floor" type="number" min="0" step="0.01" defaultValue="0" /></label>
          </div>
          <label className="check-label"><input name="redirect_cash_above_floor" type="checkbox" value="true" /> Redirect projected cash above the floor to investments</label>
          <div className="field-row">
            <label>Bonus amount<input name="bonus_amount" type="number" min="0" step="0.01" defaultValue="0" /></label>
            <label>Bonus month<input name="bonus_month" type="month" /></label>
          </div>
          <label>Optional annual return scenario %<input name="annual_return_pct" type="number" min="-100" max="100" step="0.1" defaultValue="0" /></label>
          <button className="primary-button" disabled={busy}>{busy ? "Calculating…" : "Build comparison"}</button>
          <p className="fine-print">Comparisons never move money. Assumed returns stay separate.</p>
        </form>
        <div className="comparison-list">
          {scenarios.filter((item) => !item.is_baseline).map((scenario) => (
            <article className="panel comparison-card" key={scenario.id}>
              <span className="eyebrow">Comparison</span>
              <h2>{scenario.name}</h2>
              <div><span>Ending cash</span><strong>{currency(scenario.periods.at(-1)?.ending_cash)}</strong></div>
              <div><span>Added employee retirement</span><strong>{currency(String(scenario.periods.reduce((sum, row) => sum + Number(row.employee_retirement ?? 0), 0)))}</strong></div>
              <div><span>Cash redirected</span><strong>{currency(String(scenario.periods.reduce((sum, row) => sum + Number(row.cash_redirect_to_investments ?? 0), 0)))}</strong></div>
              <div><span>Assumed market result</span><strong>{currency(String(scenario.periods.reduce((sum, row) => sum + Number(row.assumed_investment_result ?? 0), 0)))}</strong></div>
              <ForecastChart periods={scenario.periods} />
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export function ImportView({
  data,
  onImport,
  onReport,
  busy,
  message,
}: {
  data: DashboardData;
  onImport: () => void;
  onReport: () => void;
  busy: boolean;
  message: string;
}) {
  return (
    <div className="view-stack">
      <section className="page-heading">
        <span className="eyebrow">Private data</span>
        <h1>Manual import stays first-class.</h1>
        <p>Files never leave this Mac. Reimporting the same bytes cannot create duplicates.</p>
      </section>
      <section className="import-grid">
        <article className="panel import-card">
          <span className="local-badge">127.0.0.1 only</span>
          <h2>Import private inbox</h2>
          <p>Scan payroll PDFs and canonical SoFi/Fidelity CSV or XLSX ledgers under <code>.local/inbox/</code>.</p>
          <button className="primary-button" onClick={onImport} disabled={busy}>{busy ? "Scanning…" : "Import private inbox"}</button>
          {message && <p className="action-message">{message}</p>}
        </article>
        <article className="panel import-card">
          <span className="local-badge quiet">Print friendly</span>
          <h2>Trailing-12 report</h2>
          <p>Generate a deterministic local HTML report under <code>.local/reports/</code>.</p>
          <button className="secondary-button" onClick={onReport}>Generate report</button>
        </article>
      </section>
      <section className="panel">
        <header className="section-heading"><div><span className="eyebrow">Import history</span><h2>Idempotent batches</h2></div></header>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Batch</th><th>Created</th><th>Discovered</th><th>Imported</th><th>Duplicates</th><th>Status</th></tr></thead>
            <tbody>
              {data.imports.map((batch) => (
                <tr key={batch.id}><td>#{batch.id}</td><td>{new Date(batch.created_at).toLocaleString()}</td><td>{batch.discovered}</td><td>{batch.imported}</td><td>{batch.duplicates}</td><td><StatusPill status={batch.status} /></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
