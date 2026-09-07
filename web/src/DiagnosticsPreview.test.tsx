import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DiagnosticsPreview from "./DiagnosticsPreview";

describe("Diagnostics summary", () => {
  it("distinguishes missing, failed and passed checks without exposing internal fields", () => {
    const internal = { schema_revision: "0009_goal_persistence", source_commit: "synthetic-source", contract: "internal-contract" };
    const { rerender, container } = render(<DiagnosticsPreview diagnostics={internal} />);
    expect(screen.queryByText("Passed")).not.toBeInTheDocument();
    expect(container).not.toHaveTextContent("0009_goal_persistence");
    expect(container).not.toHaveTextContent("synthetic-source");
    expect(container).not.toHaveTextContent("internal-contract");
    rerender(<DiagnosticsPreview diagnostics={{ ...internal, database_checks: { integrity: "fail", foreign_keys: "pass" }, backup_verification: { count: 0, all_verified: true } }} />);
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("No backups yet")).toBeInTheDocument();
    expect(screen.queryByText("Passed")).not.toBeInTheDocument();
    rerender(<DiagnosticsPreview diagnostics={{ database_checks: { integrity: "pass", foreign_keys: "pass" }, backup_verification: { count: 2, all_verified: true }, data_home_phase: "already_migrated", data_mode: "disposable synthetic" }} />);
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("2 checked")).toBeInTheDocument();
    expect(screen.getByText("Ready to use")).toBeInTheDocument();
    expect(screen.getByText("Temporary sample data")).toBeInTheDocument();
  });
});
