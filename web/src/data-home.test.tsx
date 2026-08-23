import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import DataHomePanel, { type DataHomeStatus } from "./data-home";

const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete window.__MONEY_MAP_DESKTOP__;
});

function nativeShell(selection: DataHomeStatus | null = null) {
  window.__MONEY_MAP_DESKTOP__ = {
    mode: true,
    reload: vi.fn(),
    print: vi.fn(),
    runtimeStatus: vi.fn(),
    restart: vi.fn(),
    about: vi.fn(),
    selectImport: vi.fn(async () => selection),
    revealBackup: vi.fn(),
  };
}

describe("desktop data-home workflow", () => {
  it("offers only explicit fresh setup or native existing-data selection", async () => {
    nativeShell({
      state: "eligible_legacy_source",
      ready: false,
      candidate_token: "synthetic-preview-token",
      source: "Eligible legacy data",
      schema: "Eligible legacy schema",
      size: 4096,
      integrity: "passed",
      foreign_keys: "passed",
      backup: "required before activation",
      destination: "ready",
      rehearsal: "required",
      rollback: "not yet available",
      candidate: "source identity reviewed",
      action: "Run synthetic rehearsal",
    });
    const onStatus = vi.fn();
    render(
      <DataHomePanel
        initial={{ phase: "fresh_setup_available", ready: false }}
        onStatus={onStatus}
      />,
    );

    expect(screen.getByRole("button", { name: "Start fresh" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Import existing Money Map data" }));

    await waitFor(() => expect(window.__MONEY_MAP_DESKTOP__?.selectImport).toHaveBeenCalledOnce());
    expect(onStatus).toHaveBeenCalledWith(expect.objectContaining({
      state: "eligible_legacy_source",
    }));
    expect(screen.getByText("Cutover readiness")).toBeVisible();
    expect(screen.queryByText(/\/Users\//)).not.toBeInTheDocument();
  });

  it("requires a separate confirmation and makes cancel a no-request action", async () => {
    nativeShell();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const onStatus = vi.fn();
    render(
      <DataHomePanel
        initial={{
          state: "eligible_legacy_source",
          ready: false,
          candidate_token: "synthetic-preview-token",
          source: "Eligible legacy data",
          schema: "Eligible legacy schema",
          size: 8192,
          integrity: "passed",
          foreign_keys: "passed",
          backup: "required before activation",
          destination: "ready",
          rehearsal: "required",
          rollback: "not yet available",
          candidate: "source identity reviewed",
          action: "Run synthetic rehearsal",
        }}
        onStatus={onStatus}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledWith({ phase: "fresh_setup_available", ready: false });
  });

  it("runs the disposable rehearsal before exposing one-use activation", async () => {
    nativeShell();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/cutover/rehearsal")) {
        return json({ state: "rehearsal_passed", rehearsal: "passed" });
      }
      if (url.endsWith("/cutover/prepare")) {
        return json({
          state: "confirmation_required",
          confirmation_token: "invented-one-use-confirmation-token-0001",
          source: "Reviewed Money Map data",
          schema: "Current 0009 candidate after rehearsal",
          backup: "verified",
          destination: "ready",
          rehearsal: "passed",
          rollback: "not required for empty destination",
          candidate: "candidate identity bound",
          action: "Confirm activation",
          expires_in_seconds: 300,
        });
      }
      if (url.endsWith("/backups")) return json({ backups: [] });
      return json({ state: "completed_cutover", ready: true });
    });
    render(
      <DataHomePanel
        initial={{
          state: "eligible_legacy_source",
          candidate_token: "invented-preview-token",
          source: "Eligible legacy data",
          schema: "Eligible legacy schema",
          size: 4096,
          integrity: "passed",
          foreign_keys: "passed",
          backup: "required before activation",
          destination: "ready",
          rehearsal: "required",
          rollback: "not yet available",
          candidate: "source identity reviewed",
          action: "Run synthetic rehearsal",
        }}
        onStatus={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run rehearsal and review confirmation" }));
    expect(await screen.findByRole("heading", { name: "Confirm cutover" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Activate reviewed data" }));
    await waitFor(() => expect(window.__MONEY_MAP_DESKTOP__?.restart).toHaveBeenCalledOnce());
    expect(window.__MONEY_MAP_DESKTOP__?.reload).toHaveBeenCalledOnce();
  });

  it("reports backend completion before setup succeeds", async () => {
    nativeShell();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      json({
        phase: "activation_complete",
        ready: true,
        schema_revision: "0009_goal_persistence",
      }),
    );
    const onStatus = vi.fn();
    render(
      <DataHomePanel
        initial={{ phase: "fresh_setup_available", ready: false }}
        onStatus={onStatus}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Start fresh" }));

    await waitFor(() => expect(onStatus).toHaveBeenCalledWith(expect.objectContaining({
      phase: "activation_complete",
      ready: true,
    })));
    expect(window.__MONEY_MAP_DESKTOP__?.restart).toHaveBeenCalledOnce();
    expect(window.__MONEY_MAP_DESKTOP__?.reload).toHaveBeenCalledOnce();
  });

  it("creates, reveals, previews, and confirms verified restore", async () => {
    nativeShell();
    const backup = {
      backup_id: "0123456789abcdef01234567",
      filename: "paycheck-map-manual-synthetic.sqlite3",
      label: "manual",
      created_at: "2026-08-21T12:00:00Z",
      schema_revision: "0009_goal_persistence",
      size: 4096,
      verified: true,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/backups")) return json({ backups: [backup] });
      if (url.endsWith("/restore-preview")) {
        return json({
          phase: "restore_preview",
          ready: true,
          backup_id: backup.backup_id,
          confirmation_token: "synthetic-restore-confirmation-token-0001",
          replacement_warning: "Restore replaces the current Money Map database.",
        });
      }
      if (url.endsWith("/restore")) {
        return json({
          phase: "restore_complete",
          ready: true,
          schema_revision: "0009_goal_persistence",
        });
      }
      return json({ phase: "backup_verified", ready: true });
    });
    render(
      <DataHomePanel
        initial={{
          phase: "already_migrated",
          ready: true,
          schema_revision: "0009_goal_persistence",
        }}
        onStatus={vi.fn()}
      />,
    );

    const item = await screen.findByRole("listitem");
    fireEvent.click(within(item).getByRole("button", { name: "Reveal in Finder" }));
    expect(window.__MONEY_MAP_DESKTOP__?.revealBackup).toHaveBeenCalledWith(backup.backup_id);
    fireEvent.click(within(item).getByRole("button", { name: "Preview restore" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(
      "Restore replaces the current Money Map database.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Replace with verified backup" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(window.__MONEY_MAP_DESKTOP__?.restart).toHaveBeenCalledOnce();
    expect(window.__MONEY_MAP_DESKTOP__?.reload).toHaveBeenCalledOnce();
  });

  it("announces safe recovery actions without exposing an exception", () => {
    nativeShell();
    render(
      <DataHomePanel
        initial={{
          phase: "recoverable_failure",
          ready: false,
          recoverable: true,
          resume_available: true,
          rollback_available: true,
          failure_code: "operation_interrupted",
        }}
        onStatus={vi.fn()}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The operation paused safely.");
    expect(within(alert).getByRole("button", { name: "Resume" })).toBeEnabled();
    expect(within(alert).getByRole("button", { name: "Roll back" })).toBeEnabled();
    expect(alert).not.toHaveTextContent("Traceback");
  });

  it("moves focus into the modal, closes with Escape, and restores invoking focus", async () => {
    nativeShell();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ backups: [] }));
    const invoking = document.createElement("button");
    invoking.textContent = "Open data safety";
    document.body.append(invoking);
    invoking.focus();
    const onClose = vi.fn();
    render(
      <DataHomePanel
        initial={{ phase: "already_migrated", ready: true, schema_revision: "0009_goal_persistence" }}
        onStatus={vi.fn()}
        onClose={onClose}
      />,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Create backup" })).toHaveFocus());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    cleanup();
    expect(invoking).toHaveFocus();
    invoking.remove();
  });
});
