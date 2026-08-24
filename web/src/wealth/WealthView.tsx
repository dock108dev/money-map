import { useState } from "react";

import { currencyExact, shortDate, signedCurrencyExact } from "../format";
import type { WealthDashboard } from "../types";
import "./wealth.css";

function roleLabel(role: string) {
  return role.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div className="wealth-metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

export default function WealthView({ data }: { data: WealthDashboard }) {
  const [periodKey, setPeriodKey] = useState("observed");
  const selectedPeriod = data.fidelity.performance_periods.find((period) => period.key === periodKey) ?? data.fidelity.performance_periods[0];
  const historyValues = data.fidelity.history.map((point) => Number(point.value ?? 0));
  const historyMin = historyValues.length ? Math.min(...historyValues) : 0;
  const historyMax = historyValues.length ? Math.max(...historyValues) : 1;
  const historyRange = Math.max(historyMax - historyMin, 1);
  const fundedAccounts = data.fidelity.accounts.filter((account) => Number(account.current_value ?? 0) !== 0);
  const observation = data.fidelity.recent_observation;
  const hasWealthEvidence = Boolean(
    data.as_of || data.accessible.accounts.length || data.fidelity.accounts.length || data.fidelity.history.length || data.paycheck,
  );

  if (!hasWealthEvidence) {
    return (
      <div className="view-stack wealth-view concise-wealth" data-copy-budget="wealth-hero-result">
        <section className="simple-page-heading"><div><span className="eyebrow">Money you can use and investments you can measure</span><h1>Wealth</h1></div></section>
        <section className="panel compact-panel empty-state" role="status">
          <h2>Wealth unavailable</h2>
          <p>No account value evidence has been imported. Use Add account to add a supported account or value, then return to Wealth.</p>
        </section>
      </div>
    );
  }

  return (
    <div className="view-stack wealth-view concise-wealth" data-copy-budget="wealth-hero-result">
      <section className="wealth-access-hero" aria-labelledby="wealth-title">
        <div className="wealth-access-total">
          <span>Accessible wealth</span>
          <h1 id="wealth-title" data-prose>Wealth</h1>
          <strong>{currencyExact(data.accessible.total)}</strong>
          {data.as_of && <small>As of {shortDate(data.as_of)}</small>}
        </div>
        <div className="wealth-access-breakdown">
          <Metric label="Cash" value={currencyExact(data.accessible.cash)} />
          <Metric label="Sellable investments" value={currencyExact(data.accessible.sellable_investments)} />
          <Metric label="Excluded" value={currencyExact(data.excluded.total)} note="Retirement + restricted" />
        </div>
      </section>
      <p className="print-only print-evidence-header" aria-hidden="true">Wealth evidence · {data.as_of ? shortDate(data.as_of) : "Date unavailable"}</p>

      <section className="panel fidelity-performance-panel concise-performance" aria-labelledby="fidelity-result-title">
        <header className="fidelity-performance-heading">
          <div><span className="eyebrow">Fidelity</span><h2 id="fidelity-result-title">{currencyExact(data.fidelity.current_value)}</h2></div>
        </header>
        <div className="performance-period-tabs print-hidden" role="group" aria-label="Fidelity performance period">
          {data.fidelity.performance_periods.map((period) => <button className={period.key === selectedPeriod?.key ? "active" : ""} key={period.key} onClick={() => setPeriodKey(period.key)}>{period.label}</button>)}
        </div>
        {selectedPeriod ? (
          <div className={`performance-result performance-${selectedPeriod.status}`}>
            <div className="performance-result-primary">
              <span>{selectedPeriod.status === "available" ? "Investment result" : "Performance unavailable"}</span>
              <strong>{selectedPeriod.status === "available" ? signedCurrencyExact(selectedPeriod.investment_result) : "Tracking"}</strong>
              <small data-prose>{selectedPeriod.status === "available" && selectedPeriod.return_pct ? `${Number(selectedPeriod.return_pct).toFixed(2)}% after contributions` : selectedPeriod.message}</small>
            </div>
          </div>
        ) : <p className="performance-unavailable" role="status" data-prose>Investment performance is unavailable for every period.</p>}
      </section>

      <details className="panel wealth-evidence evidence-disclosure">
        <summary>Fidelity evidence and methodology</summary>
        <div className="wealth-evidence-stack">
          {data.paycheck && (
            <section>
              <h2>Paycheck funding</h2>
              <div className="wealth-paycheck-grid">
                <Metric label="Spendable cash" value={currencyExact(data.paycheck.spendable_cash)} />
                <Metric label="Sellable stock funding" value={currencyExact(data.paycheck.accessible_stock_funding)} />
                <Metric label="Locked funding" value={currencyExact(data.paycheck.locked_account_funding)} note="401(k), HSA + employer" />
                <Metric label="Total paycheck value" value={currencyExact(data.paycheck.total_paycheck_value)} />
              </div>
            </section>
          )}
          <section>
            <h2>Contribution-adjusted result</h2>
            <p>Deposits and withdrawals are removed before investment gain or loss is calculated.</p>
            {selectedPeriod && <div className="performance-equation"><div><span>Opening</span><strong>{currencyExact(selectedPeriod.opening_value)}</strong></div><b>+</b><div><span>Deposits</span><strong>{currencyExact(selectedPeriod.deposits)}</strong></div><b>−</b><div><span>Withdrawals</span><strong>{currencyExact(selectedPeriod.withdrawals)}</strong></div><b>+</b><div><span>Market result</span><strong>{selectedPeriod.investment_result ? signedCurrencyExact(selectedPeriod.investment_result) : "Unavailable"}</strong></div><b>=</b><div><span>Current</span><strong>{currencyExact(selectedPeriod.closing_value)}</strong></div></div>}
          </section>
          <section className="fidelity-observation-grid">
            <div className="recent-observation-card"><span className="eyebrow">Latest observed movement</span>{observation ? <><strong>{signedCurrencyExact(observation.change)}</strong><small>{Number(observation.change_pct ?? 0).toFixed(2)}% · {shortDate(observation.period_start)}–{shortDate(observation.period_end)}</small><p>{observation.message}</p></> : <p>Missing source evidence: a second synchronized value is required.</p>}</div>
            <div className="fidelity-history-card"><span className="eyebrow">Observed Fidelity value</span><div className="wealth-history-chart" aria-label="Observed Fidelity value history">{data.fidelity.history.map((point) => { const height = 22 + ((Number(point.value ?? 0) - historyMin) / historyRange) * 78; return <div key={point.date}><i style={{ height: `${height}%` }} /><small>{shortDate(point.date)}</small></div>; })}</div></div>
          </section>
          <section>
            <h2>Fidelity accounts</h2>
            <div className="wealth-account-list">{fundedAccounts.map((account) => <div className="wealth-account-row" key={account.id}><span className={`wealth-access-dot access-${account.access_status}`} /><span className="wealth-account-name"><strong>{account.name}</strong><small>{roleLabel(account.type)} · {account.access_reason}</small></span><span className={`wealth-access-badge access-${account.access_status}`}>{account.access_status === "accessible" ? "Accessible" : account.access_status === "restricted" ? "Restricted" : account.access_status === "retirement" ? "Retirement" : roleLabel(account.access_status)}</span><span className="wealth-account-movement"><small>After contributions</small><strong>{account.performance_status === "available" ? signedCurrencyExact(account.investment_result) : "Unavailable"}</strong><em>Recent {signedCurrencyExact(account.recent_change)}</em></span><strong className="wealth-account-value">{currencyExact(account.current_value)}</strong></div>)}</div>
          </section>
          <section className="wealth-funding-evidence"><h2>Payroll funding</h2><p>{currencyExact(data.fidelity.funding.total_payroll_funding)} total · {currencyExact(data.fidelity.funding.you_contributed)} you · {currencyExact(data.fidelity.funding.employer_contributed)} employer</p></section>
        </div>
      </details>
      <button className="secondary-button wealth-print-button print-hidden" onClick={() => window.print()}>Print evidence</button>
    </div>
  );
}
