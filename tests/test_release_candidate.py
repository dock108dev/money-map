from __future__ import annotations

import copy
import json

import pytest

from paycheck_map.product_metadata import PUBLIC_VERSION, PYTHON_PACKAGE_VERSION
from paycheck_map.release_candidate import (
    ACCEPTED_STATE,
    CAMPAIGNS,
    CANDIDATE_STATE,
    FINAL_FIELDS,
    OWNER_FIELDS,
    OWNER_VALIDATIONS,
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
    assert value["campaigns"] == dict.fromkeys(CAMPAIGNS)
    assert value["owner_validations"] == dict.fromkeys(OWNER_VALIDATIONS)
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
        (("campaigns", {**dict.fromkeys(CAMPAIGNS), "A": "passed"}), "blank"),
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


def test_missing_campaign_owner_and_final_results_block_promotion() -> None:
    value = manifest()
    value["release_state"] = ACCEPTED_STATE
    with pytest.raises(ReleaseContractError, match="production-mode"):
        validate_promotion(value)
    value["build_mode"] = "production"
    with pytest.raises(ReleaseContractError, match="Campaigns"):
        validate_promotion(value)
    value["campaigns"] = dict.fromkeys(CAMPAIGNS, "passed")
    with pytest.raises(ReleaseContractError, match="owner validations"):
        validate_promotion(value)
    value["owner_validations"] = dict.fromkeys(OWNER_VALIDATIONS, "passed")
    with pytest.raises(ReleaseContractError, match="owner fields"):
        validate_promotion(value)


def test_owner_responses_are_never_generated_and_promotion_copy_fails_closed() -> None:
    value = manifest()
    original = copy.deepcopy(value)
    with pytest.raises(ReleaseContractError):
        promotion_copy(value, build_mode="production")
    assert value == original
    assert value["owner"] == dict.fromkeys(OWNER_FIELDS)


def test_final_hashes_cannot_be_copied_from_diagnostics_or_historical_evidence() -> None:
    value = manifest()
    value["release_state"] = ACCEPTED_STATE
    value["build_mode"] = "production"
    value["campaigns"] = dict.fromkeys(CAMPAIGNS, "passed")
    value["owner_validations"] = dict.fromkeys(OWNER_VALIDATIONS, "passed")
    value["owner"] = dict.fromkeys(OWNER_FIELDS, "owner-supplied")
    value["cutover_result"] = "passed"
    value["final_decision"] = "accepted"
    value["claims"] = {
        **value["claims"],  # type: ignore[dict-item]
        "campaigns_a_through_j_passed": True,
        "owner_validation_passed": True,
        "owner_cutover_completed": True,
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
