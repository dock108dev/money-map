import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FailureBoundary, reportRenderFailure } from "./FailureBoundary";

function BrokenView(): never {
  throw new Error("PRIVATE-RENDER-CANARY");
}

describe("render failure recovery", () => {
  it("keeps normal views available", () => {
    render(<FailureBoundary><p>Working view</p></FailureBoundary>);
    expect(screen.getByText("Working view")).toBeInTheDocument();
  });

  it("shows a safe recovery action and logs only a fixed code", () => {
    const output = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const reload = vi.fn();
    try {
      render(<FailureBoundary onReload={reload}><BrokenView /></FailureBoundary>, {
        onCaughtError: reportRenderFailure,
      });
      expect(screen.getByRole("alert")).not.toHaveTextContent("PRIVATE-RENDER-CANARY");
      expect(output).toHaveBeenCalledWith("MM-UI-RENDER-FAIL");
      expect(JSON.stringify(output.mock.calls)).not.toContain("PRIVATE-RENDER-CANARY");
      fireEvent.click(screen.getByRole("button", { name: "Reload Money Map" }));
      expect(reload).toHaveBeenCalledOnce();
    } finally {
      output.mockRestore();
    }
  });
});
