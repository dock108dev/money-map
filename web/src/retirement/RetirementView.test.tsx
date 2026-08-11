import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { goalProgram } from "../goals/fixtures";
import type { RetirementProjectionResult } from "../v2-contracts";
import { COPY_BUDGETS, proseWordCount } from "../copy-budget";
import RetirementView from "./RetirementView";
import {
  retirementProfile,
  retirementRun,
  retirementSnapshot,
  retirementStartingPoint,
} from "./test-fixtures";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

function retirementFetch(options: { staleEdit?: boolean; unavailable?: boolean; snapshots?: Array<typeof retirementSnapshot>; forcedStatus?: RetirementProjectionResult["bridge_verdict"] } = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/v2/retirement/profile" && init?.method === "PUT") {
      if (options.staleEdit) return json({ detail: "The Retirement profile changed" }, 409);
      return json({ ...retirementProfile, retirement_flexible_monthly_spend: { ...retirementProfile.retirement_flexible_monthly_spend, amount: "2500.00" }, edit_token: "x".repeat(64) });
    }
    if (url === "/api/v2/retirement/profile") return json(retirementProfile);
    if (url === "/api/v2/retirement/starting-point") {
      return json(options.unavailable ? { ...retirementStartingPoint, accessible_total: null, pretax_retirement: null } : retirementStartingPoint);
    }
    if (url === "/api/v2/retirement/operational-goals") return json([goalProgram]);
    if (url === "/api/v2/retirement/project") {
      const body = JSON.parse(String(init?.body)) as { path: "middle" | "rough" | "early_crash"; goal_program_id: string | null };
      const status = options.forcedStatus ?? (body.path === "rough" ? "works_essentials_only" : body.path === "early_crash" ? "insufficient_accessible_bridge" : "works");
      return json(retirementRun(status, Boolean(body.goal_program_id)));
    }
    if (url === "/api/v2/retirement/snapshots" && init?.method === "POST") return json(retirementSnapshot);
    if (url === "/api/v2/retirement/snapshots") return json(options.snapshots ?? [retirementSnapshot]);
    if (url === "/api/v2/retirement/snapshots/11") return json(retirementSnapshot);
    return new Response("Not found", { status: 404 });
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Retirement", () => {
  it("opens with operational goals excluded, a first-viewport verdict, chart, and collapsed assumptions", async () => {
    vi.stubGlobal("fetch", retirementFetch());
    render(<RetirementView />);
    expect(await screen.findByRole("heading", { name: "Retirement" })).toBeInTheDocument();
    expect(screen.getByText("Test when work can become optional.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Works" })).toBeInTheDocument();
    expect(screen.getAllByText("Operational goals excluded")).toHaveLength(1);
    expect(screen.getByRole("option", { name: "Do not include a goal" })).toBeInTheDocument();
    expect(screen.getByText("Accessible at work stop")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /three deterministic paths/ })).toBeInTheDocument();
    const assumptions = screen.getByText("Assumptions and starting evidence").closest("details");
    expect(assumptions).not.toHaveAttribute("open");
    expect(screen.queryByText("See when work can become optional under explicit assumptions.")).not.toBeInTheDocument();
    expect(screen.queryByText(/Compound sprint/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Promotion preview/)).not.toBeInTheDocument();
    const budget = document.querySelector('[data-copy-budget="retirement-before-chart"]');
    expect(budget).not.toBeNull();
    expect(proseWordCount(budget!)).toBeLessThanOrEqual(COPY_BUDGETS["retirement-before-chart"]);
  });

  it.each([
    ["Rough path", "Essentials hold"],
    ["Early-crash path", "Bridge breaks"],
  ] as const)("shows the %s bridge verdict", async (path, heading) => {
    vi.stubGlobal("fetch", retirementFetch());
    render(<RetirementView />);
    await screen.findByRole("heading", { name: "Works" });
    fireEvent.change(screen.getByLabelText("Retirement path"), { target: { value: path === "Rough path" ? "rough" : "early_crash" } });
    fireEvent.click(screen.getByRole("button", { name: "Run projection" }));
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("keeps a textual Retirement shortfall in the primary answer", async () => {
    vi.stubGlobal("fetch", retirementFetch({ forcedStatus: "shortfall" }));
    render(<RetirementView />);
    expect(await screen.findByRole("heading", { name: "Shortfall" })).toBeInTheDocument();
    expect(screen.getByText("Required retirement spending cannot remain funded.")).toBeInTheDocument();
    expect(screen.getByText(/Test another age, path, or assumption/)).toBeInTheDocument();
  });

  it("includes one named immutable goal only after selection and switches to the annual table", async () => {
    const fetch = retirementFetch();
    vi.stubGlobal("fetch", fetch);
    render(<RetirementView />);
    await screen.findByRole("heading", { name: "Works" });
    fireEvent.change(screen.getByLabelText("Operational goal inclusion"), { target: { value: goalProgram.goal_program_id } });
    fireEvent.click(screen.getByRole("button", { name: "Run projection" }));
    expect(await screen.findByText(`${goalProgram.name} · immutable goal snapshot`)).toBeInTheDocument();
    const projectCall = [...fetch.mock.calls].reverse().find(([input]) => String(input) === "/api/v2/retirement/project");
    expect(projectCall?.[1]?.body).toContain(goalProgram.goal_program_id);
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByText("Work optional")).not.toHaveLength(0);
  });

  it("saves and opens stored evidence without rerunning it", async () => {
    const fetch = retirementFetch();
    vi.stubGlobal("fetch", fetch);
    render(<RetirementView />);
    await screen.findByRole("heading", { name: "Works" });
    const before = fetch.mock.calls.filter(([input]) => String(input) === "/api/v2/retirement/project").length;
    fireEvent.click(screen.getByRole("button", { name: "Save snapshot" }));
    fireEvent.change(screen.getByLabelText("Snapshot name"), { target: { value: "Owner run" } });
    fireEvent.click(within(screen.getByRole("dialog", { name: "Save Retirement snapshot" })).getByRole("button", { name: "Save snapshot" }));
    expect(await screen.findByText("Retirement snapshot saved.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Retirement snapshot evidence"));
    fireEvent.click(screen.getByRole("button", { name: /Age 43 middle/ }));
    expect(await screen.findByRole("heading", { name: "Age 43 middle" })).toBeInTheDocument();
    expect(screen.getByText(/Stored snapshot · original result/)).toBeInTheDocument();
    expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/v2/retirement/project")).toHaveLength(before);
  });

  it("keeps stale profile edits open with an associated error and shows unavailable evidence explicitly", async () => {
    vi.stubGlobal("fetch", retirementFetch({ staleEdit: true, unavailable: true }));
    render(<RetirementView />);
    await screen.findByRole("heading", { name: "Works" });
    fireEvent.click(screen.getByRole("button", { name: "Edit assumptions" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Retirement assumptions" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save assumptions" }));
    const error = await within(dialog).findByRole("alert");
    expect(error).toHaveTextContent("Retirement profile changed");
    expect(within(dialog).getByRole("form", { name: "Retirement profile assumptions" })).toHaveAttribute("aria-describedby", error.id);
    fireEvent.click(screen.getByText("Assumptions and starting evidence"));
    await waitFor(() => expect(screen.getAllByText("Unavailable").length).toBeGreaterThanOrEqual(2));
  });

  it("limits visible snapshot history to three, searches all saved evidence, and reports empty results", async () => {
    const snapshots = Array.from({ length: 5 }, (_, index) => ({
      ...retirementSnapshot,
      id: index + 20,
      name: index === 4 ? "Far future owner case" : `Recent case ${index + 1}`,
      created_at: `2026-08-${String(index + 1).padStart(2, "0")}T12:00:00Z`,
    }));
    vi.stubGlobal("fetch", retirementFetch({ snapshots }));
    render(<RetirementView />);
    await screen.findByRole("heading", { name: "Works" });
    fireEvent.click(screen.getByText("Retirement snapshot evidence"));
    expect(document.querySelectorAll(".retirement-snapshot-list > button")).toHaveLength(3);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search saved Retirement evidence" }), { target: { value: "Far future" } });
    expect(screen.getByRole("button", { name: /Far future owner case/ })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search saved Retirement evidence" }), { target: { value: "missing" } });
    expect(screen.getByText("No saved Retirement evidence matches this search.")).toBeInTheDocument();
  });

  it("enters the assumptions sheet, traps focus, closes on Escape, and returns focus", async () => {
    vi.stubGlobal("fetch", retirementFetch());
    render(<RetirementView />);
    await screen.findByRole("heading", { name: "Works" });
    const trigger = screen.getByRole("button", { name: "Edit assumptions" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Edit Retirement assumptions" });
    expect(within(dialog).getByLabelText("Date of birth")).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("prints dated Retirement evidence with exact run and snapshot fingerprints", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", retirementFetch());
    render(<RetirementView />);
    await screen.findByRole("heading", { name: "Works" });
    fireEvent.click(screen.getByRole("button", { name: "Print evidence" }));
    expect(print).toHaveBeenCalledOnce();
    expect(document.querySelector(".print-evidence-header")).toHaveTextContent("Retirement evidence · 2026-08-10");
    expect(document.querySelector(".retirement-verdict .print-only")).toHaveTextContent(`Run fingerprint: ${"d".repeat(64)}`);
    expect(document.querySelector(".retirement-snapshot-list .print-only")).toHaveTextContent(`Fingerprint: ${retirementSnapshot.source_fingerprint}`);
    expect(screen.getByText("Assumptions and starting evidence").closest("details")).not.toHaveAttribute("open");
  });
});
