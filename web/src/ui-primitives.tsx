import type { ReactNode } from "react";

import { currencyExact, shortDate } from "./format";
import type { AccountActivity, AccountsDashboard } from "./types";

export function StatusPill({ status }: { status: string }) {
  return <span className={`status status-${status}`}>{status.replaceAll("_", " ")}</span>;
}

export function EmptyState({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">○</div><h3>{title}</h3><p>{children}</p>{action}</div>;
}

export function MetricCard({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: string }) {
  return <article className={`metric-card ${tone ?? ""}`}><span className="eyebrow">{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</article>;
}

export const roleLabel = (role: string) =>
  role.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

export const activityPeriod = (data: AccountsDashboard) => {
  if (!data.activity_period.start || !data.activity_period.end) return "Imported activity";
  return `${shortDate(data.activity_period.start)}–${shortDate(data.activity_period.end)}`;
};

export function ActivityRows({ rows }: { rows: AccountActivity[] }) {
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
