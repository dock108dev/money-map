import { useEffect, useState, type FormEvent } from "react";

import { addAccountValue, loadAccountDetail } from "../api";
import { currency, currencyExact, monthLabel, shortDate } from "../format";
import type { AccountDetail as AccountDetailData, AccountsDashboard, ConnectedAccount } from "../types";
import { ActivityRows, EmptyState, MetricCard, activityPeriod, roleLabel } from "../ui-primitives";

const categoryLabel: Record<ConnectedAccount["category"], string> = {
  cash: "Cash", investment: "Investments", debt: "Debt", other: "Other",
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
        <strong>{data.accounts.length ? `${currency(data.totals.net_worth)} net worth` : "Net worth unavailable"}</strong>
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
  showOlder = false,
}: {
  data: AccountsDashboard;
  period?: { startDate: string; endDate: string } | null;
  showOlder?: boolean;
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
        <ActivityRows rows={showOlder ? rows : rows.slice(0, 5)} />
      </section>
    </div>
  );
}

const toCents = (value: string | null | undefined) =>
  value == null ? 0 : Math.round(Number(value) * 100);

const fromCents = (value: number) => (value / 100).toFixed(2);
