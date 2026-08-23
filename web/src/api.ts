import type { AccountDetail, DashboardData, PlaidRefreshResult, PlaidStatus } from "./types";
import {
  validateCashFlowPeriodResult,
  validateGoalGapPreviewResponse,
  validateRecurringOutflowCandidateList,
  type CashFlowPeriodResult,
  type GoalGapPreviewRequest,
  type GoalGapPreviewResponse,
  type PeriodKind,
  type RecurringOutflowCandidateList,
} from "./v21-contracts";

export type ApplicationData = Pick<
  DashboardData,
  "accounts" | "wealth" | "issues" | "plaid" | "payroll" | "scenarios" | "imports"
>;

export interface CashFlowRequest {
  periodKind: PeriodKind;
  startDate?: string;
  endDate?: string;
}

export class CashFlowUnavailableError extends Error {
  readonly status = 409;

  constructor(readonly reason: string) {
    super(reason);
    this.name = "CashFlowUnavailableError";
  }
}

export class CashFlowValidationError extends Error {
  readonly status = 422;

  constructor(message: string) {
    super(message);
    this.name = "CashFlowValidationError";
  }
}

export class CashFlowApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "CashFlowApiError";
  }
}

export class GoalGapApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "GoalGapApiError";
  }
}

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

export async function loadDashboard(): Promise<ApplicationData> {
  const [accounts, wealth, issues, plaid, payroll, scenarios, imports] = await Promise.all([
    request<DashboardData["accounts"]>("/api/accounts"),
    request<DashboardData["wealth"]>("/api/wealth"),
    request<DashboardData["issues"]>("/api/exceptions"),
    request<DashboardData["plaid"]>("/api/plaid/status"),
    request<DashboardData["payroll"]>("/api/payroll"),
    request<DashboardData["scenarios"]>("/api/scenarios"),
    request<DashboardData["imports"]>("/api/imports"),
  ]);
  return {
    accounts,
    wealth,
    issues,
    plaid,
    payroll,
    scenarios,
    imports,
  };
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "object" && item !== null && "msg" in item) {
          const message = (item as { msg?: unknown }).msg;
          return typeof message === "string" ? message : null;
        }
        return null;
      })
      .filter((item): item is string => Boolean(item));
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

export async function loadCashFlow({
  periodKind,
  startDate,
  endDate,
}: CashFlowRequest): Promise<CashFlowPeriodResult> {
  const query = new URLSearchParams({ period_kind: periodKind });
  if (startDate !== undefined) query.set("start_date", startDate);
  if (endDate !== undefined) query.set("end_date", endDate);
  const response = await fetch(`/api/v2/cash-flow?${query}`);
  const body = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? (body as { detail?: unknown }).detail
        : null;
    if (response.status === 409) {
      const reason =
        typeof detail === "object" && detail !== null && "reason" in detail
          ? (detail as { reason?: unknown }).reason
          : null;
      throw new CashFlowUnavailableError(
        typeof reason === "string" && reason.trim() ? reason : "Cash Flow is unavailable.",
      );
    }
    if (response.status === 422) {
      throw new CashFlowValidationError(
        detailMessage(detail, "The selected Cash Flow period is invalid."),
      );
    }
    throw new CashFlowApiError(
      response.status,
      detailMessage(detail, `Cash Flow request failed (${response.status}).`),
    );
  }
  try {
    return validateCashFlowPeriodResult(body);
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : "Unknown contract error";
    throw new CashFlowApiError(0, `Cash Flow evidence was invalid: ${detail}`);
  }
}

export async function previewGoalGap(
  payload: GoalGapPreviewRequest,
): Promise<GoalGapPreviewResponse> {
  const response = await fetch("/api/v2/goals/gap-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? (body as { detail?: unknown }).detail
        : null;
    throw new GoalGapApiError(
      response.status,
      detailMessage(detail, `Goal-gap preview failed (${response.status}).`),
    );
  }
  try {
    return validateGoalGapPreviewResponse(body);
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : "Unknown contract error";
    throw new GoalGapApiError(0, `Goal-gap evidence was invalid: ${detail}`);
  }
}

export async function loadRecurringOutflowCandidates(): Promise<RecurringOutflowCandidateList> {
  const response = await fetch("/api/v2/cash-flow/recurring-outflow-candidates");
  const body = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? (body as { detail?: unknown }).detail
        : null;
    throw new GoalGapApiError(
      response.status,
      detailMessage(detail, `Repeated-outflow candidates failed (${response.status}).`),
    );
  }
  try {
    return validateRecurringOutflowCandidateList(body);
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : "Unknown contract error";
    throw new GoalGapApiError(0, `Repeated-outflow evidence was invalid: ${detail}`);
  }
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
  return request<{ report_id: string; filename: string }>("/api/reports/trailing-12", {
    method: "POST",
  });
}

export function configurePlaid(payload: {
  environment: "sandbox" | "production";
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
