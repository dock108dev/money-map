import pytest

from paycheck_map.desktop_policy import (
    ACCEPTANCE_DATA_MODE,
    DISPOSABLE_DATA_MODE,
    KEYCHAIN_ACCEPTANCE_DATA_MODE,
    MANAGED_DATA_MODES,
    PRODUCTION_DATA_MODE,
    uses_managed_data_home,
    uses_memory_secret_store,
)
from paycheck_map.product_metadata import (
    PUBLIC_VERSION,
    PYTHON_PACKAGE_VERSION,
    SCHEMA_HEAD,
    desktop_artifact_name,
)

from .conftest import PROJECT_ROOT


@pytest.mark.parametrize(
    "mode",
    [PRODUCTION_DATA_MODE, ACCEPTANCE_DATA_MODE, KEYCHAIN_ACCEPTANCE_DATA_MODE],
)
def test_managed_desktop_modes_share_one_policy(mode: str) -> None:
    assert mode in MANAGED_DATA_MODES
    assert uses_managed_data_home(mode)


def test_unsupported_and_disposable_modes_do_not_enter_managed_data_home() -> None:
    assert not uses_managed_data_home(DISPOSABLE_DATA_MODE)
    assert not uses_managed_data_home("production")
    assert not uses_managed_data_home(None)
    assert uses_memory_secret_store(ACCEPTANCE_DATA_MODE)
    assert uses_memory_secret_store(KEYCHAIN_ACCEPTANCE_DATA_MODE)
    assert not uses_memory_secret_store(PRODUCTION_DATA_MODE)


def test_product_identity_is_derived_from_authoritative_metadata() -> None:
    assert PUBLIC_VERSION == "3.0.0-beta.1"
    assert PYTHON_PACKAGE_VERSION == "3.0.0b1"
    assert SCHEMA_HEAD == "0009_goal_persistence"
    assert desktop_artifact_name() == f"Money Map-{PUBLIC_VERSION}-arm64.dmg"


def test_policy_callers_do_not_reintroduce_mode_lists() -> None:
    callers = (
        "src/paycheck_map/app.py",
        "src/paycheck_map/api.py",
        "src/paycheck_map/config.py",
        "src/paycheck_map/data_home.py",
        "src/paycheck_map/desktop_sidecar.py",
    )
    managed_literals = tuple(MANAGED_DATA_MODES)
    for relative in callers:
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert sum(literal in source for literal in managed_literals) <= 1, relative


def test_frontend_does_not_invent_the_backend_schema() -> None:
    source = (PROJECT_ROOT / "web/src/data-home.tsx").read_text(encoding="utf-8")
    assert SCHEMA_HEAD not in source
    assert 'status.schema_revision ?? "unavailable"' in source


def test_release_scripts_source_python_identity_from_product_metadata() -> None:
    for relative in (
        "scripts/package_desktop_release.py",
        "scripts/qualify_desktop_release.py",
    ):
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert 'VERSION = "3.0.0-beta.1"' not in source
        assert 'SCHEMA = "0009_goal_persistence"' not in source
