from __future__ import annotations

import copy
import json

import pytest

from paycheck_map.product_metadata import PUBLIC_VERSION, PYTHON_PACKAGE_VERSION
from paycheck_map.release_candidate import (
    ACCEPTED_STATE,
    CANDIDATE_STATE,
    FINAL_FIELDS,
    OPTIONAL_SOAK_FIELDS,
    OWNER_FIELDS,
    QUALIFICATION_GATES,
    ReleaseContractError,
    candidate_manifest,
    promotion_copy,
    validate_candidate,
    validate_promotion,
)

from .conftest import PROJECT_ROOT


def manifest() -> dict[str, object]:
    return candidate_manifest(
        source_commit="a" * 40,
        clean_tree=True,
        bundle_identifier="com.moneymap.desktop",
        architecture="aarch64-apple-darwin",
        signing_identity="Apple Development",
        entitlements=[],
        oracle_digest="b" * 64,
        normalized_payload_identity="c" * 64,
        app_identity="d" * 64,
        dmg_identity="e" * 64,
    )


def test_candidate_is_explicitly_not_accepted_and_every_result_is_blank() -> None:
    value = manifest()
    assert value["release_state"] == CANDIDATE_STATE
    assert value["version_mapping"] == {
        "public": PUBLIC_VERSION,
        "python": PYTHON_PACKAGE_VERSION,
    }
    assert value["schema_revision"] == "0009_goal_persistence"
    assert value["qualification_gates"] == dict.fromkeys(QUALIFICATION_GATES)
    assert value["optional_soak"] == dict.fromkeys(OPTIONAL_SOAK_FIELDS)
    assert value["owner"] == dict.fromkeys(OWNER_FIELDS)
    assert value["final"] == dict.fromkeys(FINAL_FIELDS)
    assert value["cutover_result"] is None
    assert value["final_decision"] is None
    assert value["signing"] == {
        "identity_class": "Apple Development",
        "entitlements": [],
        "notarized": False,
        "stapled": False,
        "external_distribution_approved": False,
    }
    claims = value["claims"]
    assert isinstance(claims, dict)
    assert not any(claims.values())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("release_state", ACCEPTED_STATE), "cannot claim acceptance"),
        (("schema_revision", "0010_forbidden"), "schema"),
        (("version_mapping", {"public": "3.0.0", "python": "3.0.0"}), "version"),
        (
            (
                "qualification_gates",
                {**dict.fromkeys(QUALIFICATION_GATES), "complete_headless_gate": "passed"},
            ),
            "blank",
        ),
        (("owner", {**dict.fromkeys(OWNER_FIELDS), "acceptance": "accepted"}), "blank"),
        (("cutover_result", "passed"), "decisions"),
        (("historical_evidence_promotion", True), "historical"),
    ],
)
def test_candidate_rejects_inconsistent_acceptance_schema_version_and_owner_combinations(
    mutation: tuple[str, object], message: str
) -> None:
    value = manifest()
    value[mutation[0]] = mutation[1]
    with pytest.raises(ReleaseContractError, match=message):
        validate_candidate(value)


def test_missing_bounded_gate_owner_cutover_decision_and_final_results_block_promotion() -> None:
    value = manifest()
    value["release_state"] = ACCEPTED_STATE
    with pytest.raises(ReleaseContractError, match="bounded owner-beta"):
        validate_promotion(value)
    for gate in QUALIFICATION_GATES:
        incomplete = copy.deepcopy(value)
        incomplete["qualification_gates"] = dict.fromkeys(QUALIFICATION_GATES, "passed")
        incomplete["qualification_gates"][gate] = None  # type: ignore[index]
        with pytest.raises(ReleaseContractError, match="bounded owner-beta"):
            validate_promotion(incomplete)
    value["qualification_gates"] = dict.fromkeys(QUALIFICATION_GATES, "passed")
    with pytest.raises(ReleaseContractError, match="owner fields"):
        validate_promotion(value)
    value["owner"] = dict.fromkeys(OWNER_FIELDS, "owner-supplied")
    with pytest.raises(ReleaseContractError, match="cutover and final decision"):
        validate_promotion(value)
    value["cutover_result"] = "passed"
    with pytest.raises(ReleaseContractError, match="cutover and final decision"):
        validate_promotion(value)
    value["final_decision"] = "accepted"
    with pytest.raises(ReleaseContractError, match="final identities"):
        validate_promotion(value)
    for field in FINAL_FIELDS:
        incomplete = accepted_manifest()
        incomplete["final"][field] = None  # type: ignore[index]
        with pytest.raises(ReleaseContractError, match="final identities"):
            validate_promotion(incomplete)


def test_optional_matrix_and_retired_campaign_soak_never_promote_or_block() -> None:
    optional_only = manifest()
    optional_only["release_state"] = ACCEPTED_STATE
    optional_only["optional_soak"] = dict.fromkeys(OPTIONAL_SOAK_FIELDS, "passed")
    with pytest.raises(ReleaseContractError, match="bounded owner-beta"):
        validate_promotion(optional_only)

    value = accepted_manifest()
    value["optional_soak"] = {
        "state_route_221_matrix": "not_run_optional",
        "retired_campaigns_c_through_j": "failed_optional",
    }
    validate_promotion(value)


def test_owner_responses_are_never_generated_and_promotion_copy_fails_closed() -> None:
    value = manifest()
    original = copy.deepcopy(value)
    with pytest.raises(ReleaseContractError):
        promotion_copy(value)
    assert value == original
    assert value["owner"] == dict.fromkeys(OWNER_FIELDS)


def test_final_hashes_cannot_be_copied_from_diagnostics_or_historical_evidence() -> None:
    value = manifest()
    value["release_state"] = ACCEPTED_STATE
    value["qualification_gates"] = dict.fromkeys(QUALIFICATION_GATES, "passed")
    value["owner"] = dict.fromkeys(OWNER_FIELDS, "owner-supplied")
    value["cutover_result"] = "passed"
    value["final_decision"] = "accepted"
    value["claims"] = {
        **value["claims"],  # type: ignore[dict-item]
        "bounded_owner_beta_qualification_passed": True,
        "owner_cutover_completed": True,
        "final_owner_decision_recorded": True,
        "accepted_as_beta": True,
        "tagged": True,
    }
    value["final"] = {
        "accepted_commit": "a" * 40,
        "final_app_hash": "diagnostic-artifact",
        "final_dmg_hash": "diagnostic-artifact",
        "final_tag": "v3.0.0-beta.1",
        "release_date": "pending-owner-decision",
    }
    with pytest.raises(ReleaseContractError, match="identities"):
        validate_promotion(value)
    value["historical_evidence_promotion"] = True
    with pytest.raises(ReleaseContractError):
        validate_promotion(value)


def accepted_manifest() -> dict[str, object]:
    value = manifest()
    value["release_state"] = ACCEPTED_STATE
    value["qualification_gates"] = dict.fromkeys(QUALIFICATION_GATES, "passed")
    value["owner"] = dict.fromkeys(OWNER_FIELDS, "owner-supplied")
    value["cutover_result"] = "passed"
    value["final_decision"] = "accepted"
    value["claims"] = {
        **value["claims"],  # type: ignore[dict-item]
        "bounded_owner_beta_qualification_passed": True,
        "owner_cutover_completed": True,
        "final_owner_decision_recorded": True,
        "accepted_as_beta": True,
        "tagged": True,
    }
    value["final"] = {
        "accepted_commit": "a" * 40,
        "final_app_hash": "d" * 64,
        "final_dmg_hash": "e" * 64,
        "final_tag": "v3.0.0-beta.1",
        "release_date": "2026-08-26",
    }
    return value


def test_release_notes_and_campaign_manifest_keep_final_and_owner_fields_pending() -> None:
    notes = (PROJECT_ROOT / "docs/releases/v3.0.0-beta.1.md").read_text(encoding="utf-8")
    campaign = json.loads(
        (PROJECT_ROOT / "docs/releases/v3.0.0-beta.1-final-campaign.json").read_text(
            encoding="utf-8"
        )
    )
    for field in (
        "Accepted commit: pending",
        "Final app hash: pending",
        "Final DMG hash: pending",
        "Owner acceptance: pending",
        "Final tag: pending",
        "Release date: pending",
    ):
        assert field in notes
    assert campaign["release_state"] == CANDIDATE_STATE
    assert campaign["promotion_gates"] == dict.fromkeys(QUALIFICATION_GATES)
    assert campaign["results"] == dict.fromkeys(campaign["steps"])
    assert campaign["owner_responses"] == dict.fromkeys(campaign["owner_responses"])


def test_schema_and_private_data_boundaries_remain_frozen() -> None:
    assert not list((PROJECT_ROOT / "alembic/versions").glob("0010*.py"))
    for path in (
        PROJECT_ROOT / "docs/releases/v3.0.0-beta.1-final-campaign.json",
        PROJECT_ROOT / "docs/releases/v3.0.0-beta.1.md",
    ):
        content = path.read_text(encoding="utf-8")
        assert "/Users/" not in content
        assert "owner source identity: pending" in content.lower() or path.suffix == ".json"
