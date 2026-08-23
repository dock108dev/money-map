from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "scripts/preflight_slice6_source_matrix.py"


def load_preflight() -> ModuleType:
    spec = importlib.util.spec_from_file_location("slice6_source_preflight", PREFLIGHT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sealed_221_combination_source_preflight_has_no_obvious_mismatch() -> None:
    report = load_preflight().materialize_diagnostic()
    assert report["result"] == "pass", report["first_mismatch"]
    assert report["combination_count"] == 221
    assert report["source_assertion_count"] == 2687
    assert report["deterministic_empty_copy_combinations"] == 13
    assert report["installed_only_assertion_count"] == 208
    assert report["mismatches"] == []
    assert report["candidate_output_used_as_expectation"] is False
    assert report["oracle_updated"] is False
