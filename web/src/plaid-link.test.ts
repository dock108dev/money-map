import { afterEach, expect, it, vi } from "vitest";
import { openPlaidLink } from "./plaid-link";

afterEach(() => { delete window.Plaid; });

it("does not expose provider-controlled error text", async () => {
  const destroy = vi.fn();
  window.Plaid = { create: (options) => ({
    open: () => options.onExit({ error_code: "PRIVATE-CODE", display_message: "PRIVATE-DISPLAY", error_message: "PRIVATE-ERROR" }),
    destroy,
  }) };
  const operation = openPlaidLink("synthetic-link-token", vi.fn());
  await expect(operation).rejects.toThrow("Plaid Link could not complete the connection");
  await expect(operation).rejects.not.toThrow("PRIVATE");
  expect(destroy).toHaveBeenCalledOnce();
});

it("preserves cancellation as a normal no-op", async () => {
  window.Plaid = { create: (options) => ({ open: () => options.onExit(null), destroy: vi.fn() }) };
  await expect(openPlaidLink("synthetic-link-token", vi.fn())).resolves.toBeUndefined();
});
