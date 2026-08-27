"""Release-candidate manifest and fail-closed promotion contract for Money Map 3.0."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from .product_metadata import PUBLIC_VERSION, PYTHON_PACKAGE_VERSION, SCHEMA_HEAD

RELEASE_CONTRACT = "money-map-v3-release-manifest-v1"
CANDIDATE_STATE = "candidate_not_accepted"
ACCEPTED_STATE = "accepted"
QUALIFICATION_GATES = (
    "complete_headless_gate",
    "exact_candidate_build",
    "two_cycle_installed_smoke",
    "short_owner_synthetic_walkthrough",
)
OPTIONAL_SOAK_FIELDS = (
    "state_route_221_matrix",
    "retired_campaigns_c_through_j",
)
OWNER_FIELDS = (
    "source_identity",
    "pre_cutover_backup",
    "post_cutover_manifest",
    "acceptance",
)
FINAL_FIELDS = (
    "accepted_commit",
    "final_app_hash",
    "final_dmg_hash",
    "final_tag",
    "release_date",
)
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class ReleaseContractError(RuntimeError):
    """A candidate manifest is internally inconsistent or not promotable."""


def candidate_manifest(
    *,
    source_commit: str,
    clean_tree: bool,
    bundle_identifier: str,
    architecture: str,
    signing_identity: str,
    entitlements: list[str],
    oracle_digest: str,
    normalized_payload_identity: str | None = None,
    app_identity: str | None = None,
    dmg_identity: str | None = None,
    build_mode: str = "qualification",
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "contract": RELEASE_CONTRACT,
        "release_state": CANDIDATE_STATE,
        "source_commit": source_commit,
        "clean_tree": clean_tree,
        "version_mapping": {"public": PUBLIC_VERSION, "python": PYTHON_PACKAGE_VERSION},
        "schema_revision": SCHEMA_HEAD,
        "bundle_identifier": bundle_identifier,
        "architecture": architecture,
        "signing": {
            "identity_class": signing_identity,
            "entitlements": list(entitlements),
            "notarized": False,
            "stapled": False,
            "external_distribution_approved": False,
        },
        "build_mode": build_mode,
        "normalized_payload_identity": normalized_payload_identity,
        "app_identity": app_identity,
        "dmg_identity": dmg_identity,
        "oracle_digest": oracle_digest,
        "qualification_gates": {gate: None for gate in QUALIFICATION_GATES},
        "optional_soak": {field: None for field in OPTIONAL_SOAK_FIELDS},
        "owner": {field: None for field in OWNER_FIELDS},
        "cutover_result": None,
        "final_decision": None,
        "final": {field: None for field in FINAL_FIELDS},
        "claims": {
            "bounded_owner_beta_qualification_passed": False,
            "owner_cutover_completed": False,
            "final_owner_decision_recorded": False,
            "accepted_as_beta": False,
            "tagged": False,
            "published": False,
        },
        "historical_evidence_promotion": False,
    }
    validate_candidate(manifest)
    return manifest


def validate_candidate(manifest: Mapping[str, Any]) -> None:
    if manifest.get("contract") != RELEASE_CONTRACT:
        raise ReleaseContractError("release manifest contract mismatch")
    if manifest.get("release_state") != CANDIDATE_STATE:
        raise ReleaseContractError("candidate manifests cannot claim acceptance")
    if not HEX_40.fullmatch(str(manifest.get("source_commit", ""))) or not manifest.get(
        "clean_tree"
    ):
        raise ReleaseContractError("candidate source identity is incomplete")
    if manifest.get("version_mapping") != {
        "public": PUBLIC_VERSION,
        "python": PYTHON_PACKAGE_VERSION,
    }:
        raise ReleaseContractError("version mapping is inconsistent")
    if manifest.get("schema_revision") != SCHEMA_HEAD:
        raise ReleaseContractError("schema is inconsistent")
    if manifest.get("build_mode") not in {"qualification", "production"}:
        raise ReleaseContractError("build mode is invalid")
    if not HEX_64.fullmatch(str(manifest.get("oracle_digest", ""))):
        raise ReleaseContractError("oracle digest is invalid")
    signing = manifest.get("signing")
    if (
        not isinstance(signing, Mapping)
        or signing.get("identity_class") not in {"Apple Development", "Developer ID Application"}
        or signing.get("notarized")
        or signing.get("stapled")
        or signing.get("external_distribution_approved")
    ):
        raise ReleaseContractError("candidate signing claims are inconsistent")
    qualification_gates = manifest.get("qualification_gates")
    optional_soak = manifest.get("optional_soak")
    owner = manifest.get("owner")
    final = manifest.get("final")
    if not isinstance(qualification_gates, Mapping) or qualification_gates != dict.fromkeys(
        QUALIFICATION_GATES
    ):
        raise ReleaseContractError("bounded qualification gate results must remain blank")
    if not isinstance(optional_soak, Mapping) or optional_soak != dict.fromkeys(
        OPTIONAL_SOAK_FIELDS
    ):
        raise ReleaseContractError("optional soak results must remain blank")
    if not isinstance(owner, Mapping) or owner != dict.fromkeys(OWNER_FIELDS):
        raise ReleaseContractError("owner fields must remain blank")
    if not isinstance(final, Mapping) or final != dict.fromkeys(FINAL_FIELDS):
        raise ReleaseContractError("final fields must remain blank")
    if manifest.get("cutover_result") is not None or manifest.get("final_decision") is not None:
        raise ReleaseContractError("candidate decisions must remain blank")
    claims = manifest.get("claims")
    if not isinstance(claims, Mapping) or any(bool(value) for value in claims.values()):
        raise ReleaseContractError("candidate claims must all be false")
    if manifest.get("historical_evidence_promotion") is not False:
        raise ReleaseContractError("historical evidence cannot promote this candidate")


def validate_promotion(manifest: Mapping[str, Any]) -> None:
    if (
        manifest.get("contract") != RELEASE_CONTRACT
        or manifest.get("release_state") != ACCEPTED_STATE
    ):
        raise ReleaseContractError("an accepted manifest is required")
    if manifest.get("version_mapping") != {
        "public": PUBLIC_VERSION,
        "python": PYTHON_PACKAGE_VERSION,
    }:
        raise ReleaseContractError("version mapping is inconsistent")
    if manifest.get("schema_revision") != SCHEMA_HEAD:
        raise ReleaseContractError("schema is inconsistent")
    if manifest.get("build_mode") not in {"qualification", "production"}:
        raise ReleaseContractError("candidate build mode is invalid")
    for identity in (
        "normalized_payload_identity",
        "app_identity",
        "dmg_identity",
        "oracle_digest",
    ):
        if not HEX_64.fullmatch(str(manifest.get(identity, ""))):
            raise ReleaseContractError(f"final {identity} is missing")
    if set(manifest.get("qualification_gates", {})) != set(QUALIFICATION_GATES) or any(
        value != "passed" for value in manifest["qualification_gates"].values()
    ):
        raise ReleaseContractError("bounded owner-beta qualification gates are incomplete")
    optional_soak = manifest.get("optional_soak")
    if not isinstance(optional_soak, Mapping) or set(optional_soak) != set(OPTIONAL_SOAK_FIELDS):
        raise ReleaseContractError("optional soak schema is inconsistent")
    owner = manifest.get("owner", {})
    if set(owner) != set(OWNER_FIELDS) or any(not value for value in owner.values()):
        raise ReleaseContractError("owner fields are incomplete")
    if manifest.get("cutover_result") != "passed" or manifest.get("final_decision") != "accepted":
        raise ReleaseContractError("cutover and final decision are incomplete")
    final = manifest.get("final", {})
    if set(final) != set(FINAL_FIELDS) or any(not value for value in final.values()):
        raise ReleaseContractError("final identities are incomplete")
    if (
        final["final_app_hash"] != manifest["app_identity"]
        or final["final_dmg_hash"] != manifest["dmg_identity"]
        or final["accepted_commit"] != manifest["source_commit"]
    ):
        raise ReleaseContractError("final identities do not match the accepted artifacts")
    claims = manifest.get("claims", {})
    required_claims = {
        "bounded_owner_beta_qualification_passed",
        "owner_cutover_completed",
        "final_owner_decision_recorded",
        "accepted_as_beta",
        "tagged",
    }
    if any(claims.get(claim) is not True for claim in required_claims):
        raise ReleaseContractError("accepted claims are incomplete")
    if claims.get("published") is not False:
        raise ReleaseContractError("external publication requires separate authorization")
    if manifest.get("historical_evidence_promotion") is not False:
        raise ReleaseContractError("historical evidence cannot promote this candidate")


def promotion_copy(candidate: Mapping[str, Any], **updates: Any) -> dict[str, Any]:
    """Build an explicit proposed acceptance record; never fills owner or result fields."""

    validate_candidate(candidate)
    promoted = copy.deepcopy(dict(candidate))
    promoted.update(updates)
    promoted["release_state"] = ACCEPTED_STATE
    validate_promotion(promoted)
    return promoted
