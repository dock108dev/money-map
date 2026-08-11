import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { goalProgram } from "../goals/fixtures";
import RetirementView from "./RetirementView";
import {
  retirementProfile,
  retirementRun,
  retirementSnapshot,
  retirementStartingPoint,
} from "./test-fixtures";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

function retirementFetch(options: { staleEdit?: boolean; unavailable?: boolean } = {}) {
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
      const status = body.path === "rough" ? "works_essentials_only" : body.path === "early_crash" ? "insufficient_accessible_bridge" : "works";
      return json(retirementRun(status, Boolean(body.goal_program_id)));
    }
    if (url === "/api/v2/retirement/snapshots" && init?.method === "POST") return json(retirementSnapshot);
    if (url === "/api/v2/retirement/snapshots") return json([retirementSnapshot]);
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
    expect(screen.getByText("See when work can become optional under explicit assumptions.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Works" })).toBeInTheDocument();
    expect(screen.getAllByText("Operational goals excluded")).toHaveLength(2);
    expect(screen.getByText("Accessible assets at work stop")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /three deterministic paths/ })).toBeInTheDocument();
    const assumptions = screen.getByText("Assumptions and starting-point evidence").closest("details");
    expect(assumptions).not.toHaveAttribute("open");
    expect(screen.queryByText(/Compound sprint/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Promotion preview/)).not.toBeInTheDocument();
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
    expect(screen.getByText("Work optional")).toBeInTheDocument();
  });

  it("saves and opens stored evidence without rerunning it", async () => {
    const fetch = retirementFetch();
    vi.stubGlobal("fetch", fetch);
    render(<RetirementView />);
    await screen.findByRole("heading", { name: "Works" });
    const before = fetch.mock.calls.filter(([input]) => String(input) === "/api/v2/retirement/project").length;
    fireEvent.change(screen.getByLabelText("Retirement snapshot name"), { target: { value: "Owner run" } });
    fireEvent.click(screen.getByRole("button", { name: "Save snapshot" }));
    expect(await screen.findByText("Reproducible Retirement snapshot saved.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Age 43 middle/ }));
    expect(await screen.findByRole("heading", { name: "Age 43 middle" })).toBeInTheDocument();
    expect(screen.getByText(/was not rerun/)).toBeInTheDocument();
    expect(fetch.mock.calls.filter(([input]) => String(input) === "/api/v2/retirement/project")).toHaveLength(before);
  });

  it("keeps stale profile edits open with an associated error and shows unavailable evidence explicitly", async () => {
    vi.stubGlobal("fetch", retirementFetch({ staleEdit: true, unavailable: true }));
    render(<RetirementView />);
    await screen.findByRole("heading", { name: "Works" });
    fireEvent.click(screen.getByRole("button", { name: "Edit assumptions" }));
    const dialog = screen.getByRole("dialog", { name: "Edit the durable profile" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save assumptions" }));
    const error = await within(dialog).findByRole("alert");
    expect(error).toHaveTextContent("Retirement profile changed");
    expect(within(dialog).getByRole("form", { name: "Retirement profile assumptions" })).toHaveAttribute("aria-describedby", error.id);
    fireEvent.click(screen.getByText("Assumptions and starting-point evidence"));
    await waitFor(() => expect(screen.getAllByText("Unavailable").length).toBeGreaterThanOrEqual(2));
  });
});
