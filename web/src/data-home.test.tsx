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
      phase: "confirmation_required",
      ready: false,
      candidate_token: "synthetic-preview-token",
      source_classification: "selected existing Money Map data",
      schema_revision: "0009_goal_persistence",
      size: 4096,
      confirmation_required: true,
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
      phase: "confirmation_required",
      confirmation_required: true,
    }));
    expect(screen.getByText("Migration preview")).toBeVisible();
    expect(screen.queryByText(/\/Users\//)).not.toBeInTheDocument();
  });

  it("requires a separate confirmation and makes cancel a no-request action", async () => {
    nativeShell();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const onStatus = vi.fn();
    render(
      <DataHomePanel
        initial={{
          phase: "confirmation_required",
          ready: false,
          candidate_token: "synthetic-preview-token",
          source_classification: "selected existing Money Map data",
          schema_revision: "0008_life_lab_v01",
          size: 8192,
        }}
        onStatus={onStatus}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledWith({ phase: "fresh_setup_available", ready: false });
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
});
