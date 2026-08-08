import type { AccountDetail, DashboardData, PlaidRefreshResult, PlaidStatus } from "./types";

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function loadDashboard(): Promise<DashboardData> {
  const [overview, accounts, wealth, issues, plaid, payroll, timeline, scenarios, imports] = await Promise.all([
      request<DashboardData["overview"]>("/api/overview"),
      request<DashboardData["accounts"]>("/api/accounts"),
      request<DashboardData["wealth"]>("/api/wealth"),
      request<DashboardData["issues"]>("/api/exceptions"),
      request<DashboardData["plaid"]>("/api/plaid/status"),
      request<DashboardData["payroll"]>("/api/payroll"),
      request<DashboardData["timeline"]>("/api/timeline"),
      request<DashboardData["scenarios"]>("/api/scenarios"),
      request<DashboardData["imports"]>("/api/imports"),
    ]);
  return {
    overview,
    accounts,
    wealth,
    issues,
    plaid,
    payroll,
    paychecks: [],
    timeline,
    scenarios,
    imports,
    sofi: { accounts: [], consolidated_external_net: null, internal_transfer_pairs: 0, warnings: [] },
    fidelity: { accounts: [], consolidated: {}, warnings: [] },
  };
}

export async function loadPeriod(startDate: string, endDate: string) {
  const query = new URLSearchParams({ start_date: startDate, end_date: endDate });
  const [overview, timeline] = await Promise.all([
    request<DashboardData["overview"]>(`/api/overview?${query}`),
    request<DashboardData["timeline"]>(`/api/timeline?${query}`),
  ]);
  return { overview, timeline };
}

export function loadAccountDetail(accountId: number, startDate: string, endDate: string) {
  const query = new URLSearchParams({ start_date: startDate, end_date: endDate });
  return request<AccountDetail>(`/api/accounts/${accountId}?${query}`);
}

export function addAccountValue(
  accountId: number,
  payload: { observation_date: string; value: string; source_note: string },
) {
  return request(`/api/accounts/${accountId}/values`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function importInbox() {
  return request<{ imported: number; duplicates: number; errors: Array<unknown> }>(
    "/api/imports/scan",
    { method: "POST" },
  );
}

export function createScenario(payload: Record<string, string | number | null>) {
  return request("/api/scenarios", { method: "POST", body: JSON.stringify(payload) });
}

export function createReport() {
  return request<{ path: string }>("/api/reports/trailing-12", { method: "POST" });
}

export function configurePlaid(payload: {
  environment: "sandbox" | "production";
  client_id: string;
  secret: string;
}) {
  return request<PlaidStatus["configuration"]>("/api/plaid/configuration", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createPlaidLinkToken(payload: {
  environment: "sandbox" | "production";
  target: "sofi" | "fidelity";
}) {
  return request<{
    session_id: string;
    link_token: string;
    expiration: string;
    environment: string;
    target: string;
  }>("/api/plaid/link-token", { method: "POST", body: JSON.stringify(payload) });
}

export function exchangePlaidToken(payload: { session_id: string; public_token: string }) {
  return request<{ connection_id: number; status: string; target: string }>(
    "/api/plaid/exchange",
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function syncPlaidConnection(connectionId: number) {
  return request<{ connection_id: number; status: string; last_synced_at: string }>(
    `/api/plaid/connections/${connectionId}/sync`,
    { method: "POST" },
  );
}

export function syncAllPlaidConnections(automatic = false) {
  return request<PlaidRefreshResult>("/api/plaid/sync-all", {
    method: "POST",
    body: JSON.stringify({ automatic }),
  });
}

export function updateAutoRefreshPreference(enabled: boolean) {
  return request<PlaidStatus["refresh"]>("/api/plaid/refresh-preference", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

export function createPlaidUpdateToken(connectionId: number) {
  return request<{ connection_id: number; link_token: string }>(
    `/api/plaid/connections/${connectionId}/update-token`,
    { method: "POST" },
  );
}

export function disconnectPlaidConnection(connectionId: number, deleteLocalData = true) {
  return request<{ disconnected: boolean; local_data_deleted: boolean }>(
    `/api/plaid/connections/${connectionId}?delete_local_data=${String(deleteLocalData)}`,
    { method: "DELETE" },
  );
}
