import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import HousingView from "./HousingView";
import type { AccountsDashboard } from "../types";

const accounts: AccountsDashboard = { as_of: null, activity_period: { start: null, end: null }, totals: { net_worth: "0", cash: "0", assets: "0", debts: "0", investments: "0", money_in: "0", money_out: "0", net_cash_flow: "0" }, accounts: [], activity: [] };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("creates a housing goal from empty accounts, preserves unknowns and reloads alternatives", async () => {
  let saved: unknown[] = [];
  const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      const row = { id: 1, revision: 1, plan: body.plan, updated_at: "2026-09-08", result: { scenarios: [] } };
      saved = [row];
      return new Response(JSON.stringify(row), { status: 200 });
    }
    return new Response(JSON.stringify(saved), { status: 200 });
  });
  vi.stubGlobal("fetch", fetch);
  const view = render(<HousingView accounts={accounts} navigate={vi.fn()} />);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  fireEvent.click(screen.getByText("Use Long Branch starting brief"));
  expect(screen.getByLabelText("What does that condo amount mean?")).toHaveValue("unknown");
  expect(screen.getByLabelText("Mortgage payoff at closing")).toHaveValue(null);
  fireEvent.click(screen.getByText("Copy as alternative"));
  fireEvent.change(screen.getByLabelText("Monthly rent target"), { target: { value: "4500" } });
  fireEvent.click(screen.getByText("Save housing goal"));
  await screen.findByText("Plan and all alternatives saved.");
  view.unmount();
  render(<HousingView accounts={accounts} navigate={vi.fn()} />);
  await screen.findByRole("option", { name: "Long Branch move" });
  fireEvent.change(screen.getByLabelText("Saved plans"), { target: { value: "1" } });
  expect(screen.getByLabelText("Monthly rent target")).toHaveValue(4000);
  fireEvent.change(screen.getByLabelText("Alternative"), { target: { value: "1" } });
  expect(screen.getByLabelText("Monthly rent target")).toHaveValue(4500);
  expect(screen.getByLabelText("Mortgage payoff at closing")).toHaveValue(null);
});
it("clears stale results and keeps a rejected save editable", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => init?.method ? new Response(JSON.stringify({ detail: "This plan changed elsewhere. Reopen it before saving your changes." }), { status: 409 }) : new Response("[]")));
  render(<HousingView accounts={accounts} navigate={vi.fn()} />);
  fireEvent.click(screen.getByText("Use Long Branch starting brief"));
  fireEvent.click(screen.getByText("Save housing goal"));
  await screen.findByText("This plan changed elsewhere. Reopen it before saving your changes.");
  expect(screen.getByLabelText("Destination")).toHaveValue("Long Branch");
  expect(screen.getByLabelText("Saved plans")).toBeDisabled();
  expect(screen.getByText("Discard unsaved changes")).toBeEnabled();
});

it("can replace a draft alternative with the Long Branch brief", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
  render(<HousingView accounts={accounts} navigate={vi.fn()} />);
  fireEvent.click(screen.getByText("Copy as alternative"));
  expect(screen.getByLabelText("Alternative")).toHaveValue("1");
  fireEvent.click(screen.getByText("Use Long Branch starting brief"));
  expect(screen.getByLabelText("Alternative")).toHaveValue("0");
  expect(screen.getByLabelText("Destination")).toHaveValue("Long Branch");
  expect(screen.getByLabelText("Monthly rent target")).toHaveValue(4000);
  expect(screen.queryByRole("option", { name: "Alternative 2" })).not.toBeInTheDocument();
  await waitFor(() => expect(fetch).toHaveBeenCalled());
});
