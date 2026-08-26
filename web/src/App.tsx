import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import {
  type ApplicationData,
  configurePlaid,
  createReport,
  createPlaidLinkToken,
  createPlaidUpdateToken,
  disconnectPlaidConnection,
  exchangePlaidToken,
  loadDashboard,
  importInbox,
  syncAllPlaidConnections,
  syncPlaidConnection,
  updateAutoRefreshPreference,
} from "./api";
import {
  AccountsView,
  ActivityView,
  ConnectionsView,
  IncomeView,
  ReviewView,
  WealthView,
} from "./components";
import CashFlowView from "./cash-flow/CashFlowView";
import { openPlaidLink } from "./plaid-link";
import DataHomePanel, { loadDataHomeStatus, type DataHomeStatus } from "./data-home";
import { FocusedDialog } from "./FocusedDialog";
const LifeLabView = lazy(() => import("./life-lab/LifeLabView"));
const RetirementView = lazy(() => import("./retirement/RetirementView"));
const GoalsView = lazy(() => import("./goals/GoalsView"));
const OverviewRoute = lazy(() => import("./overview/OverviewRoute"));

declare global {
  interface Window {
    __MONEY_MAP_DESKTOP__?: {
      mode: true;
      qualificationState?: "unavailable" | "partial_coverage" | "recoverable_failure" | null;
      reload(): Promise<void>;
      print(): Promise<void>;
      runtimeStatus(): Promise<DesktopRuntimeStatus>;
      restart(): Promise<DesktopRuntimeStatus>;
      about(): Promise<DesktopAboutInfo>;
      selectImport(): Promise<DataHomeStatus | null>;
      revealBackup(backupId: string): Promise<void>;
      reportAction?(reportId: string, action: "open" | "reveal"): Promise<void>;
      diagnosticsPreview?(): Promise<Record<string, unknown>>;
      exportDiagnostics?(): Promise<boolean>;
      setOperationsEnabled?(enabled: boolean): Promise<void>;
    };
  }
}

type DesktopRuntimeState = "starting" | "ready" | "failed" | "restarting" | "stopping" | "stopped";

interface DesktopRuntimeStatus {
  state: DesktopRuntimeState;
  generation: number;
  message?: string | null;
}

interface DesktopAboutInfo {
  product: string;
  runtime_version: string;
  schema_revision: string;
  release_state: "candidate / not accepted";
  desktop_build: string;
  source_commit: string;
  target: string;
  data_mode: string;
  data_location: string;
  boundary: string;
}

type View = "cash-flow" | "goals" | "overview" | "accounts" | "income" | "activity" | "wealth" | "retirement" | "lab" | "connections" | "review";

const routeByName: Readonly<Record<string, View>> = {
  "cash-flow": "cash-flow", goals: "goals", overview: "overview", accounts: "accounts",
  income: "income", activity: "activity", wealth: "wealth", retirement: "retirement",
  lab: "lab", connections: "connections", review: "review",
};

function initialView(_desktopMode: boolean): View {
  if (window.location.hash === "#plaid-live-setup") return "connections";
  if (!window.location.hash.startsWith("#view=")) return "cash-flow";
  return routeByName[window.location.hash.slice(6)] ?? "cash-flow";
}

const navGroups: Array<{ id: string; label: string; items: Array<{ id: View; label: string; glyph: string }> }> = [
  { id: "everyday", label: "Everyday", items: [
    { id: "cash-flow", label: "Cash Flow", glyph: "↕" },
    { id: "goals", label: "Goals", glyph: "◉" },
    { id: "activity", label: "Activity", glyph: "↕" },
  ] },
  { id: "details", label: "Details", items: [
    { id: "overview", label: "Overview", glyph: "⌂" },
    { id: "accounts", label: "Accounts", glyph: "▤" },
    { id: "income", label: "Income", glyph: "$" },
    { id: "wealth", label: "Wealth", glyph: "◇" },
  ] },
  { id: "planning", label: "Planning", items: [
    { id: "retirement", label: "Retirement", glyph: "◎" },
    { id: "lab", label: "Lab", glyph: "⌁" },
  ] },
  { id: "data", label: "Data", items: [
    { id: "connections", label: "Add account", glyph: "+" },
    { id: "review", label: "Review", glyph: "!" },
  ] },
];

export default function App() {
  const desktopMode = window.__MONEY_MAP_DESKTOP__?.mode === true;
  const qualificationState = window.__MONEY_MAP_DESKTOP__?.qualificationState ?? null;
  const [data, setData] = useState<ApplicationData | null>(null);
  const [desktopRuntime, setDesktopRuntime] = useState<DesktopRuntimeStatus | null>(() =>
    desktopMode ? { state: "starting", generation: 0 } : null,
  );
  const [dataHome, setDataHome] = useState<DataHomeStatus | null>(null);
  const [dataHomeError, setDataHomeError] = useState("");
  const [showDataHome, setShowDataHome] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>(() => initialView(desktopMode));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [updating, setUpdating] = useState(false);
  const [updateMessage, setUpdateMessage] = useState("");
  const [dataReloadVersion, setDataReloadVersion] = useState(0);
  const [report, setReport] = useState<{ report_id: string; filename: string } | null>(null);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [online, setOnline] = useState(() => navigator.onLine);
  const [activityPeriod, setActivityPeriod] = useState<{ startDate: string; endDate: string } | null>(null);
  const autoRefreshStarted = useRef(false);
  const activeNavButtonRef = useRef<HTMLButtonElement>(null);

  const navigateTo = useCallback((next: View) => {
    if (next === "activity") setActivityPeriod(null);
    if (desktopMode) window.history.replaceState(null, "", `#view=${next}`);
    setView(next);
  }, [desktopMode]);

  const refresh = useCallback(async () => {
    try {
      setError("");
      setData(await loadDashboard());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The local application could not load.");
    }
  }, []);

  const runGlobalRefresh = useCallback(async (automatic = false) => {
    setUpdating(true);
    if (!automatic) setUpdateMessage("");
    try {
      const result = await syncAllPlaidConnections(automatic);
      if (result.status !== "skipped") {
        const accountCount = result.connections.reduce((total, row) => total + row.accounts, 0);
        setUpdateMessage(
          result.failed > 0
            ? `${result.failed} account connection${result.failed === 1 ? "" : "s"} needs attention · no new goal observation saved`
            : result.goal_observation.status === "unavailable"
              ? `${accountCount} accounts updated · goal observation needs retry`
              : `${accountCount} accounts updated`,
        );
      }
      await refresh();
    } catch (reason) {
      const detail = reason instanceof Error ? reason.message : "Account update failed.";
      if (!detail.toLowerCase().includes("already updating")) setUpdateMessage(detail);
      await refresh();
    } finally {
      setDataReloadVersion((current) => current + 1);
      setUpdating(false);
    }
  }, [refresh]);

  const refreshDataHome = useCallback(async () => {
    setDataHomeError("");
    try {
      setDataHome(await loadDataHomeStatus());
    } catch (reason) {
      setDataHome(null);
      setDataHomeError(
        reason instanceof Error
          ? reason.message
          : "Private data readiness could not be verified.",
      );
    }
  }, []);

  useEffect(() => {
    if (!desktopMode || (desktopRuntime?.state === "ready" && dataHome?.ready)) void refresh();
  }, [dataHome?.ready, desktopMode, desktopRuntime?.generation, desktopRuntime?.state, refresh]);

  useEffect(() => {
    if (!desktopMode || desktopRuntime?.state !== "ready") return;
    void refreshDataHome();
  }, [desktopMode, desktopRuntime?.generation, desktopRuntime?.state, refreshDataHome]);

  useEffect(() => {
    if (!desktopMode) return;
    let active = true;
    let timer = 0;
    const checkRuntime = async () => {
      try {
        const status = await window.__MONEY_MAP_DESKTOP__?.runtimeStatus();
        if (active && status) setDesktopRuntime(status);
      } catch {
        if (active) setDesktopRuntime({ state: "failed", generation: 0 });
      }
      if (active) timer = window.setTimeout(() => void checkRuntime(), 250);
    };
    void checkRuntime();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [desktopMode]);

  useEffect(() => {
    const wentOffline = () => setOnline(false);
    const cameOnline = () => setOnline(true);
    window.addEventListener("offline", wentOffline);
    window.addEventListener("online", cameOnline);
    return () => {
      window.removeEventListener("offline", wentOffline);
      window.removeEventListener("online", cameOnline);
    };
  }, []);

  useEffect(() => {
    if (!desktopMode) return;
    const enabled = desktopRuntime?.state === "ready" && dataHome?.ready === true && !busy && !updating;
    void window.__MONEY_MAP_DESKTOP__?.setOperationsEnabled?.(enabled);
  }, [busy, dataHome?.ready, desktopMode, desktopRuntime?.state, updating]);

  useEffect(() => {
    if (!data || autoRefreshStarted.current || !data.plaid.refresh.automatic_refresh_due) return;
    autoRefreshStarted.current = true;
    void runGlobalRefresh(true);
  }, [data, runGlobalRefresh]);

  useEffect(() => {
    const revealActiveNavigation = () => {
      activeNavButtonRef.current?.scrollIntoView?.({ block: "nearest", inline: "center" });
    };
    window.scrollTo(0, 0);
    revealActiveNavigation();
    window.addEventListener("resize", revealActiveNavigation);
    return () => window.removeEventListener("resize", revealActiveNavigation);
  }, [view]);

  useEffect(() => {
    const openedForPrint = new Set<HTMLDetailsElement>();
    const openPrintEvidence = () => {
      document.querySelectorAll<HTMLDetailsElement>("details").forEach((detail) => {
        if (detail.open) return;
        detail.open = true;
        openedForPrint.add(detail);
      });
    };
    const restoreScreenDisclosures = () => {
      openedForPrint.forEach((detail) => { detail.open = false; });
      openedForPrint.clear();
    };
    window.addEventListener("beforeprint", openPrintEvidence);
    window.addEventListener("afterprint", restoreScreenDisclosures);
    return () => {
      window.removeEventListener("beforeprint", openPrintEvidence);
      window.removeEventListener("afterprint", restoreScreenDisclosures);
    };
  }, []);

  const runPlaidConfiguration = async (payload: {
    environment: "sandbox" | "production";
  }) => {
    setBusy(true);
    setMessage("");
    try {
      await configurePlaid(payload);
      setMessage("Plaid is ready.");
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Plaid configuration failed.");
    } finally {
      setBusy(false);
    }
  };

  const runPlaidConnect = async (
    target: "sofi" | "fidelity",
    environment: "sandbox" | "production",
  ) => {
    setBusy(true);
    setMessage("");
    try {
      const link = await createPlaidLinkToken({ target, environment });
      await openPlaidLink(link.link_token, async (publicToken) => {
        await exchangePlaidToken({ session_id: link.session_id, public_token: publicToken });
      });
      setMessage("Account connected and synced.");
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Plaid connection failed.");
    } finally {
      setBusy(false);
    }
  };

  const runPlaidSync = async (connectionId: number) => {
    setBusy(true);
    setMessage("");
    try {
      await syncPlaidConnection(connectionId);
      setMessage("Accounts updated.");
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Sync failed.");
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const runAutoRefreshPreference = async (enabled: boolean) => {
    setBusy(true);
    try {
      await updateAutoRefreshPreference(enabled);
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "The preference could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  const runPlaidRepair = async (connectionId: number) => {
    setBusy(true);
    setMessage("");
    try {
      const link = await createPlaidUpdateToken(connectionId);
      await openPlaidLink(link.link_token, async () => {
        await syncPlaidConnection(connectionId);
      });
      setMessage("Connection refreshed.");
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Reconnection failed.");
    } finally {
      setBusy(false);
    }
  };

  const runPlaidDisconnect = async (connectionId: number) => {
    setBusy(true);
    setMessage("");
    try {
      await disconnectPlaidConnection(connectionId, true);
      setMessage("Account connection removed.");
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Disconnection failed.");
    } finally {
      setBusy(false);
    }
  };

  const runImport = async () => {
    setBusy(true);
    try {
      const result = await importInbox();
      setMessage(`${result.imported} imported · ${result.duplicates} already current`);
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  };

  const runReport = async () => {
    setBusy(true);
    setMessage("Generating report…");
    try {
      const result = await createReport();
      setReport(result);
      setMessage("Report ready.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Report failed.");
    } finally {
      setBusy(false);
    }
  };

  const restartDesktopRuntime = async () => {
    const generation = desktopRuntime?.generation ?? 0;
    setDesktopRuntime({ state: "restarting", generation });
    try {
      const status = await window.__MONEY_MAP_DESKTOP__?.restart();
      if (status) setDesktopRuntime(status);
    } catch {
      setDesktopRuntime({ state: "failed", generation: generation + 1 });
    }
  };

  const previewDiagnostics = useCallback(async () => {
    setBusy(true);
    setMessage("");
    try {
      const preview = await window.__MONEY_MAP_DESKTOP__?.diagnosticsPreview?.();
      if (preview) setDiagnostics(preview);
    } catch {
      setMessage("Sanitized diagnostics are unavailable.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!desktopMode) return;
    const onMenu = (event: Event) => {
      const action = (event as CustomEvent<string>).detail;
      const routes: Record<string, View> = {
        "view-cash-flow": "cash-flow", "view-goals": "goals", "view-activity": "activity",
        "view-overview": "overview",
        "view-accounts": "accounts", "view-income": "income", "view-wealth": "wealth",
        "view-retirement": "retirement", "view-lab": "lab", "view-connections": "connections",
        "view-review": "review",
      };
      if (routes[action]) navigateTo(routes[action]);
      else if (action === "import-private-inbox") void runImport();
      else if (action === "import-existing-data" || action === "create-backup" || action === "restore-backup") setShowDataHome(true);
      else if (action === "generate-report") void runReport();
      else if (action === "print-current-view") void window.__MONEY_MAP_DESKTOP__?.print();
      else if (action === "reload-safe") void window.__MONEY_MAP_DESKTOP__?.reload();
      else if (action === "export-diagnostics") void previewDiagnostics();
      else if (action === "runtime-failed") setDesktopRuntime((current) => ({ state: "failed", generation: current?.generation ?? 0 }));
    };
    window.addEventListener("money-map-menu", onMenu);
    return () => window.removeEventListener("money-map-menu", onMenu);
  }, [desktopMode, navigateTo, previewDiagnostics]);

  if (desktopMode && desktopRuntime?.state !== "ready") {
    if (desktopRuntime?.state === "failed") {
      return (
        <main className="fatal-state" role="alert">
          <span>Local service unavailable</span>
          <h1>Money Map paused safely.</h1>
          <p>Financial data was not silently repaired or changed. Controls stay unavailable until the local service restarts.</p>
          <button className="primary-button" onClick={() => void restartDesktopRuntime()}>
            Restart local service
          </button>
        </main>
      );
    }
    return (
      <main className="loading-state" aria-live="polite">
        <div className="loading-mark">M</div>
        <p>{desktopRuntime?.state === "restarting" ? "Restarting safely…" : "Starting local service…"}</p>
      </main>
    );
  }

  if (desktopMode && dataHome && !dataHome.ready) {
    return <DataHomePanel initial={dataHome} onStatus={setDataHome} />;
  }

  if (desktopMode && desktopRuntime?.state === "ready" && dataHomeError) {
    return (
      <main className="fatal-state" role="alert">
        <span>Private data status unavailable</span>
        <h1>Money Map paused safely.</h1>
        <p>{dataHomeError}</p>
        <button className="primary-button" onClick={() => void refreshDataHome()}>
          Try again
        </button>
      </main>
    );
  }

  if (desktopMode && qualificationState === "recoverable_failure") {
    return (
      <main
        className="fatal-state"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="qualification-recovery-heading"
      >
        <span>Local connection issue</span>
        <h1 id="qualification-recovery-heading">Money Map could not load.</h1>
        <p>The last accepted local data remains unchanged.</p>
        <button className="primary-button" onClick={() => void refresh()}>
          Try again
        </button>
      </main>
    );
  }

  if (error && !data) {
    return (
      <main className="fatal-state">
        <span>Local connection issue</span>
        <h1>Money Map could not load.</h1>
        <p>{error}</p>
        <button className="primary-button" onClick={() => void refresh()}>
          Try again
        </button>
      </main>
    );
  }

  if (!data) {
    return (
      <main
        className="loading-state"
        data-qualification-loading="global-dashboard"
        aria-busy="true"
        aria-live="polite"
      >
        <div className="loading-mark" aria-hidden="true">M</div>
        <h1>Loading accounts…</h1>
      </main>
    );
  }

  const latestConnectionSync = data.plaid.connections
    .map((connection) => connection.last_synced_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);
  const latestSync = data.plaid.refresh.last_successful_refresh ?? latestConnectionSync;
  const updateNeedsAttention = /attention|failed|partial|retry|unavailable/i.test(updateMessage);
  const hasImportedFinancialEvidence =
    data.accounts.accounts.length > 0 || data.payroll.rows.length > 0;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">M</span>
          <div>
            <strong>Money Map</strong>
            <small>Everything in one place</small>
          </div>
        </div>
        <nav aria-label="Primary navigation">
          {navGroups.map((group) => (
            <div className="nav-group" role="group" aria-labelledby={`nav-group-${group.id}`} key={group.id}>
              <span className="nav-group-label" id={`nav-group-${group.id}`}>{group.label}</span>
              <div className="nav-group-items">
                {group.items
                  .filter((item) => item.id !== "review" || data.issues.length > 0)
                  .map((item) => (
                    <button
                      className={view === item.id ? "active" : ""}
                      key={item.id}
                      ref={view === item.id ? activeNavButtonRef : undefined}
                      aria-current={view === item.id ? "page" : undefined}
                      aria-label={item.id === "review" && data.issues.length > 0 ? `Review, ${data.issues.length} issues` : item.label}
                      onClick={() => {
                        navigateTo(item.id);
                      }}
                    >
                      <span aria-hidden="true">{item.glyph}</span>
                      {item.label}
                      {item.id === "review" && data.issues.length > 0 && <em>{data.issues.length}</em>}
                    </button>
                  ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="privacy-card">
          <span className="privacy-dot" />
          <div>
            <strong>{data.accounts.accounts.length} accounts</strong>
            <small>Plaid read-only</small>
          </div>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <div className="mobile-brand">Money Map</div>
          <div className="refresh-controls">
            <div className="data-state">
              <span className="privacy-dot" aria-hidden="true" />
              <span className="data-state-label">{updating
                ? "Updating…"
                : !online
                  ? "Offline · local data available"
                : latestSync
                  ? `Updated ${new Date(latestSync).toLocaleString()}`
                  : "Local data"}</span>
              {updateMessage && <small role={updateNeedsAttention ? "alert" : "status"}>{updateMessage}</small>}
            </div>
            <button
              className="refresh-button"
              disabled={updating}
              onClick={() => {
                if (data.plaid.refresh.active_connections === 0) navigateTo("connections");
                else void runGlobalRefresh(false);
              }}
            >
              {updating ? "Updating…" : "Update data"}
            </button>
            {desktopMode && (
              <>
                <button
                  className="refresh-button"
                  type="button"
                  onClick={() => void window.__MONEY_MAP_DESKTOP__?.reload()}
                >
                  Reload
                </button>
                <button
                  className="refresh-button"
                  type="button"
                  onClick={() => setShowDataHome(true)}
                >
                  Data safety
                </button>
                <button className="refresh-button" type="button" disabled={busy} onClick={() => void runReport()}>
                  Generate report
                </button>
                <button className="refresh-button" type="button" disabled={busy} onClick={() => void previewDiagnostics()}>
                  Diagnostics
                </button>
              </>
            )}
          </div>
        </header>
        {qualificationState === "unavailable" && (
          <div className="notice" role="status">
            Unavailable. No imported evidence supports this result.
          </div>
        )}
        {qualificationState === "partial_coverage" && (
          <div className="notice" role="status">
            Partial coverage. Unavailable results are withheld until missing source coverage is added.
          </div>
        )}
        {!hasImportedFinancialEvidence && (
          <div className="notice empty-data-notice" role="status">
            No imported account evidence is available yet. Use Add account to begin.
          </div>
        )}
        {error && <div className="error-banner">{error}</div>}
        <div className="content-wrap">
          {view === "cash-flow" && (
            <CashFlowView
              netWorth={data.accounts.totals.net_worth}
              reloadVersion={dataReloadVersion}
              onShowActivity={(period) => {
                setActivityPeriod(period);
                if (desktopMode) window.history.replaceState(null, "", "#view=activity");
                setView("activity");
              }}
              onShowAccounts={() => navigateTo("accounts")}
              onShowIncome={() => navigateTo("income")}
              onShowWealth={() => navigateTo("wealth")}
              onShowGoals={() => navigateTo("goals")}
            />
          )}
          {view === "goals" && (
            <Suspense fallback={<div className="loading-state"><div className="loading-mark">M</div><p>Opening Goals…</p></div>}>
              <GoalsView reloadVersion={dataReloadVersion} />
            </Suspense>
          )}
          {view === "overview" && (
            <Suspense fallback={<div className="loading-state" role="status" aria-label="Loading Overview"><div className="loading-mark">M</div><p>Opening Overview…</p></div>}>
              <OverviewRoute
                reloadVersion={dataReloadVersion}
                onShowAccounts={() => navigateTo("accounts")}
                onShowActivity={() => navigateTo("activity")}
                onShowIncome={() => navigateTo("income")}
                onShowWealth={() => navigateTo("wealth")}
                onAddAccount={() => navigateTo("connections")}
              />
            </Suspense>
          )}
          {view === "accounts" && <AccountsView data={data.accounts} />}
          {view === "income" && <IncomeView data={data.payroll} />}
          {view === "activity" && <ActivityView data={data.accounts} period={activityPeriod} />}
          {view === "wealth" && <WealthView data={data.wealth} />}
          {view === "retirement" && (
            <Suspense fallback={<div className="loading-state"><div className="loading-mark">M</div><p>Opening Retirement…</p></div>}>
              <RetirementView />
            </Suspense>
          )}
          {view === "lab" && (
            <Suspense fallback={<div className="loading-state"><div className="loading-mark">M</div><p>Opening Lab…</p></div>}>
              <LifeLabView />
            </Suspense>
          )}
          {view === "connections" && (
            <ConnectionsView
              plaid={data.plaid}
              busy={busy || updating}
              message={message}
              onConfigure={(payload) => void runPlaidConfiguration(payload)}
              onConnect={(target, environment) => void runPlaidConnect(target, environment)}
              onSync={(connectionId) => void runPlaidSync(connectionId)}
              onRepair={(connectionId) => void runPlaidRepair(connectionId)}
              onDisconnect={(connectionId) => void runPlaidDisconnect(connectionId)}
              imports={data.imports}
              onImport={() => void runImport()}
              onReport={() => void runReport()}
              onAutoRefreshChange={(enabled) => void runAutoRefreshPreference(enabled)}
            />
          )}
          {view === "review" && (
            <ReviewView
              issues={data.issues}
              busy={busy || updating}
              onUpdateData={() => void runGlobalRefresh(false)}
              onOpenAccounts={() => navigateTo("accounts")}
            />
          )}
        </div>
      </main>
      {showDataHome && dataHome && (
        <DataHomePanel initial={dataHome} onStatus={setDataHome} onClose={() => setShowDataHome(false)} />
      )}
      {report && (
        <div className="desktop-completion" role="status">
          <span>Report ready</span>
          <button type="button" onClick={() => void window.__MONEY_MAP_DESKTOP__?.reportAction?.(report.report_id, "open")}>Open Report</button>
          <button type="button" onClick={() => void window.__MONEY_MAP_DESKTOP__?.reportAction?.(report.report_id, "reveal")}>Reveal in Finder</button>
          <button type="button" aria-label="Dismiss report confirmation" onClick={() => setReport(null)}>×</button>
        </div>
      )}
      {diagnostics && (
        <FocusedDialog
          title="Sanitized diagnostics"
          description="Review the support-safe categories before choosing where to save. Financial records, paths, credentials, ports, and filenames are excluded."
          onClose={() => setDiagnostics(null)}
        >
          <dl className="diagnostics-preview">
            {Object.entries(diagnostics).map(([key, value]) => (
              <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{typeof value === "object" ? "Included safe status" : String(value)}</dd></div>
            ))}
          </dl>
          <div className="dialog-actions">
            <button type="button" onClick={() => setDiagnostics(null)}>Cancel</button>
            <button className="primary-button" type="button" onClick={async () => {
              const saved = await window.__MONEY_MAP_DESKTOP__?.exportDiagnostics?.();
              if (saved) {
                setDiagnostics(null);
                setMessage("Sanitized diagnostics exported.");
              }
            }}>Export Diagnostics</button>
          </div>
        </FocusedDialog>
      )}
    </div>
  );
}
