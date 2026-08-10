from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from paycheck_map import cli
from paycheck_map.config import Settings

from .conftest import PROJECT_ROOT


def _database(path: Path, revision: str, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (marker,))


def _revision(path: Path) -> str:
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
        return str(connection.execute("SELECT version_num FROM alembic_version").fetchone()[0])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("command", ["verify", "backup", "restore"])
def test_non_initializing_cli_commands_skip_database_initialization(
    command: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_settings = Settings(project_root=PROJECT_ROOT, local_dir=tmp_path / ".local")
    called: list[str] = []
    monkeypatch.setattr(cli, "settings", runtime_settings)
    monkeypatch.setattr(cli, "initialize_database", lambda: called.append("initialize"))
    monkeypatch.setattr(cli, "_verify", lambda: called.append("verify"))
    monkeypatch.setattr(cli, "_backup_database", lambda: tmp_path / "backup.sqlite3")
    monkeypatch.setattr(cli, "_restore_database", lambda path: tmp_path / "safety.sqlite3")
    arguments = ["paycheck-map", command]
    if command == "restore":
        arguments.append(str(tmp_path / "source.sqlite3"))
    monkeypatch.setattr(sys, "argv", arguments)

    cli.main()

    assert "initialize" not in called


def test_backup_requires_an_existing_database_without_initializing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_settings = Settings(project_root=PROJECT_ROOT, local_dir=tmp_path / ".local")
    monkeypatch.setattr(cli, "settings", runtime_settings)
    monkeypatch.setattr(
        cli,
        "initialize_database",
        lambda: pytest.fail("backup must never initialize a database"),
    )

    with pytest.raises(FileNotFoundError, match="Active database does not exist"):
        cli._backup_database()

    assert not runtime_settings.database_path.exists()


def test_backup_copies_existing_database_without_changing_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_settings = Settings(project_root=PROJECT_ROOT, local_dir=tmp_path / ".local")
    _database(runtime_settings.database_path, "0008_life_lab_v01", "active")
    active_inode = runtime_settings.database_path.stat().st_ino
    monkeypatch.setattr(cli, "settings", runtime_settings)

    backup = cli._backup_database()

    assert backup != runtime_settings.database_path
    assert backup.stat().st_ino != active_inode
    assert _revision(runtime_settings.database_path) == "0008_life_lab_v01"
    assert _revision(backup) == "0008_life_lab_v01"


def test_restore_validates_source_and_preserves_previous_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_settings = Settings(project_root=PROJECT_ROOT, local_dir=tmp_path / ".local")
    source = tmp_path / "source.sqlite3"
    _database(runtime_settings.database_path, "0008_life_lab_v01", "before")
    _database(source, "0009_goal_persistence", "restored")
    monkeypatch.setattr(cli, "settings", runtime_settings)
    monkeypatch.setattr(
        cli,
        "initialize_database",
        lambda: pytest.fail("restore must never initialize a database"),
    )

    safety_backup = cli._restore_database(source)

    assert _revision(runtime_settings.database_path) == "0009_goal_persistence"
    assert _revision(safety_backup) == "0008_life_lab_v01"
    with sqlite3.connect(
        f"file:{runtime_settings.database_path.resolve()}?mode=ro", uri=True
    ) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("restored",)
    with sqlite3.connect(f"file:{safety_backup.resolve()}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("before",)


def test_restore_rejects_active_database_hard_link(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_settings = Settings(project_root=PROJECT_ROOT, local_dir=tmp_path / ".local")
    _database(runtime_settings.database_path, "0008_life_lab_v01", "active")
    hard_link = tmp_path / "active-hard-link.sqlite3"
    hard_link.hardlink_to(runtime_settings.database_path)
    monkeypatch.setattr(cli, "settings", runtime_settings)

    with pytest.raises(ValueError, match="must not be the active database"):
        cli._restore_database(hard_link)


def test_subprocess_verify_backup_and_restore_leave_real_v1_database_at_0008(
    tmp_path: Path,
) -> None:
    local_dir = tmp_path / ".local"
    active = local_dir / "data" / "paycheck-map.sqlite3"
    active.parent.mkdir(parents=True)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{active}")
    command.upgrade(config, "0008_life_lab_v01")
    environment = os.environ.copy()
    environment["PAYCHECK_MAP_LOCAL_DIR"] = str(local_dir)
    baseline_hash = _sha256(active)

    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from paycheck_map import cli; "
                "cli._verify = lambda: None; "
                "sys.argv = ['paycheck-map', 'verify']; cli.main()"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert _revision(active) == "0008_life_lab_v01"
    assert _sha256(active) == baseline_hash

    backup_result = subprocess.run(
        [sys.executable, "-m", "paycheck_map.cli", "backup"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    backup = Path(backup_result.stdout.strip().rsplit(": ", maxsplit=1)[1])
    assert _revision(active) == "0008_life_lab_v01"
    assert _revision(backup) == "0008_life_lab_v01"
    assert _sha256(active) == baseline_hash

    restore_source = tmp_path / "restore-source.sqlite3"
    shutil.copy2(active, restore_source)
    restore_result = subprocess.run(
        [sys.executable, "-m", "paycheck_map.cli", "restore", str(restore_source)],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    safety_backup = Path(restore_result.stdout.strip().rsplit(" at ", maxsplit=1)[1])
    assert _revision(active) == "0008_life_lab_v01"
    assert _revision(safety_backup) == "0008_life_lab_v01"
