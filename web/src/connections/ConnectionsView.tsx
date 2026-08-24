import { useState } from "react";

import type { DashboardData, PlaidStatus } from "../types";
import { StatusPill } from "../ui-primitives";

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
          <h1 data-prose aria-describedby="add-account-promise">Add account</h1>
          <p id="add-account-promise" data-prose>Manual import stays first-class.</p>
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
