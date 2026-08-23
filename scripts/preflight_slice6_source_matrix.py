#!/usr/bin/env python3
"""Diagnostic source preflight for the sealed Slice 6 state-route matrix."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ORACLE_PATH = ROOT / "scripts/materialize_release_state_contract.py"
EXPECTED_DIGEST = "a8d34d04e5c56f42470fb74a6ea8dc287aa8b20ecc4237a6da76c2432202ae45"

ROUTE_SOURCES = {
    "cash-flow": ("web/src/App.tsx", "web/src/cash-flow/CashFlowView.tsx"),
    "goals": ("web/src/App.tsx", "web/src/goals/GoalsView.tsx"),
    "activity": ("web/src/App.tsx", "web/src/components.tsx"),
    "accounts": ("web/src/App.tsx", "web/src/components.tsx"),
    "income": ("web/src/App.tsx", "web/src/components.tsx"),
    "wealth": ("web/src/App.tsx", "web/src/wealth/WealthView.tsx"),
    "retirement": ("web/src/App.tsx", "web/src/retirement/RetirementView.tsx"),
    "lab": ("web/src/App.tsx", "web/src/life-lab/LifeLabView.tsx"),
    "overview": ("web/src/App.tsx", "web/src/overview/OverviewRoute.tsx", "web/src/components.tsx"),
    "add-account": ("web/src/App.tsx", "web/src/components.tsx"),
    "data-home": ("web/src/App.tsx", "web/src/data-home.tsx"),
    "diagnostics": ("web/src/App.tsx",),
    "reports": ("web/src/App.tsx",),
}


def load_oracle() -> ModuleType:
    spec = importlib.util.spec_from_file_location("slice6_release_oracle", ORACLE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("sealed oracle could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_text(route: str) -> str:
    return "\n".join((ROOT / name).read_text(encoding="utf-8") for name in ROUTE_SOURCES[route])


def normalized_route_anchor(route: str) -> str:
    if route == "add-account":
        return "connections"
    if route == "reports":
        return "generate-report"
    return route


def materialize_diagnostic() -> dict[str, Any]:
    oracle = load_oracle()
    resolved = oracle.materialize()
    if resolved["contract_digest_sha256"] != EXPECTED_DIGEST:
        raise RuntimeError("sealed oracle digest differs")

    mismatches: list[dict[str, str]] = []
    installed_only: list[dict[str, str]] = []
    assertion_count = 0
    for row in resolved["combinations"]:
        combination = str(row["combination_id"])
        route = str(row["route_id"])
        sources = source_text(route)
        anchor = normalized_route_anchor(route)
        checks = {
            "route_source_exists": route in ROUTE_SOURCES,
            "route_identity_is_anchored": anchor in sources,
            "accessible_role_is_bounded": row["expected_accessible_role"]
            in {"heading", "dialog", "button"},
            "view_open_is_declared_read_only": row["expected_write_count_on_open"] == 0,
            "network_is_local": str(row["expected_network_classification"]).startswith(
                "authenticated-ephemeral-ipv4-loopback-only"
            ),
        }
        for check, passed in checks.items():
            assertion_count += 1
            if not passed:
                mismatches.append(
                    {"combination_id": combination, "check": check, "classification": "source"}
                )

        if row["state_id"] == "empty":
            for phrase in row["expected_safe_state_language"]:
                assertion_count += 1
                if phrase not in sources:
                    mismatches.append(
                        {
                            "combination_id": combination,
                            "check": "empty_safe_state_language",
                            "classification": "source",
                            "expected": str(phrase),
                        }
                    )
        else:
            installed_only.append(
                {
                    "combination_id": combination,
                    "check": "state_dependent_rendering_and_operation_state",
                }
            )

    connections = source_text("add-account")
    exact_add_account_checks = {
        "manual_import_copy": "Manual import stays first-class." in connections,
        "manual_import_busy_only": "disabled={busy} onClick={onImport}" in connections,
        "provider_configuration_gate": "disabled={busy || !liveReady}" in connections,
        "provider_action_is_explicit": "onClick={() => onConnect(" in connections,
    }
    for check, passed in exact_add_account_checks.items():
        assertion_count += 1
        if not passed:
            mismatches.append(
                {"combination_id": "empty::add-account", "check": check, "classification": "source"}
            )

    return {
        "contract": "money-map-slice6-source-diagnostic-v1",
        "classification": "diagnostic-source-evidence-not-installed-acceptance",
        "result": "pass" if not mismatches else "failed",
        "oracle_digest_sha256": EXPECTED_DIGEST,
        "combination_count": len(resolved["combinations"]),
        "source_assertion_count": assertion_count,
        "deterministic_empty_copy_combinations": 13,
        "installed_only_assertion_count": len(installed_only),
        "first_mismatch": mismatches[0] if mismatches else None,
        "mismatches": mismatches,
        "installed_only_inventory": installed_only,
        "candidate_output_used_as_expectation": False,
        "oracle_updated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = materialize_diagnostic()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if report["mismatches"]:
        first = report["first_mismatch"]
        print(
            f"Slice 6 source preflight failed first at {first['combination_id']}: {first['check']}",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
