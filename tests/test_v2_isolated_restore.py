from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from alembic import command
from paycheck_map.config import settings
from paycheck_map.logical_manifest import build_logical_manifest, logical_tables

from .v2_migration_support import (
    assert_sqlite_health,
    database_revision,
    migration_config,
    online_copy,
    stable_v2_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_explicit_isolated_restored_copy_upgrade_downgrade_reupgrade(
    tmp_path: Path,
) -> None:
    configured = os.getenv("PAYCHECK_MAP_V2_ISOLATED_DATABASE")
    if configured is None:
        pytest.skip("explicit isolated-restored-copy drill was not requested")
    source = Path(configured).expanduser().resolve()
    assert source.is_file()
    active = settings.database_path.resolve()
    assert source != active
    if active.exists():
        assert not os.path.samefile(source, active)
    assert database_revision(source) == "0008_life_lab_v01"
    source_hash = _sha256(source)
    working = tmp_path / "isolated-restored-working.sqlite3"
    online_copy(source, working)
    before = build_logical_manifest(working)
    pre_v2_tables = set(before["tables"])
    config = migration_config(working)

    command.upgrade(config, "head")
    assert database_revision(working) == "0009_goal_persistence"
    after_upgrade = build_logical_manifest(working, include_tables=pre_v2_tables)
    assert logical_tables(after_upgrade) == logical_tables(before)
    first_v2 = stable_v2_manifest(working)
    command.downgrade(config, "0008_life_lab_v01")
    assert build_logical_manifest(working) == before
    command.upgrade(config, "head")
    assert stable_v2_manifest(working) == first_v2
    assert_sqlite_health(working)
    assert _sha256(source) == source_hash
