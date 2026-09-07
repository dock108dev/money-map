import { displayLabel } from "./presentation";

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export default function DiagnosticsPreview({ diagnostics }: { diagnostics: Record<string, unknown> }) {
  const checks = record(diagnostics.database_checks);
  const backup = record(diagnostics.backup_verification);
  const runtime = record(diagnostics.runtime);
  const dataChecks = checks.integrity === "fail" || checks.foreign_keys === "fail"
    ? "Needs attention"
    : checks.integrity === "pass" && checks.foreign_keys === "pass" ? "Passed" : "Not available";
  const backups = backup.status === "unavailable" ? "Not available"
    : backup.count === 0 ? "No backups yet"
    : typeof backup.count === "number" && backup.count > 0 && backup.all_verified === true
      ? `${backup.count} checked` : "Not verified";
  const rows = [
    ["App version", diagnostics.product_version ?? "Not available"],
    ["Release status", diagnostics.release_state === "candidate / not accepted" ? "Beta testing · final approval pending" : "Not available"],
    ["Data", diagnostics.data_mode === "disposable synthetic" ? "Temporary sample data" : diagnostics.data_mode === "private local data" ? "Your local data" : "Not available"],
    ["App status", displayLabel(runtime.state)],
    ["Data readiness", displayLabel(diagnostics.data_home_phase)],
    ["Data checks", dataChecks],
    ["Backups", backups],
    ["Connection", diagnostics.network_mode === "local_data; connected updates are explicit" ? "Data stays on this Mac. Connected accounts update when requested." : "Not available"],
    ["macOS version", diagnostics.macos_version ?? "Not available"],
  ];
  return <><dl className="diagnostics-preview">{rows.map(([label, value]) => <div key={String(label)}><dt>{String(label)}</dt><dd>{String(value)}</dd></div>)}</dl><p>Technical details for troubleshooting are included in the exported report.</p></>;
}
