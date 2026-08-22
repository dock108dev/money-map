"""Authenticated desktop-only API for the macOS data-home workflow."""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from .data_home import DataHomeError, DataHomeManager, DataHomePaths
from .db import engine

router = APIRouter(prefix="/api/desktop/data-home", tags=["desktop-data-home"])


class CandidateSelection(BaseModel):
    selected_path: str = Field(min_length=1, max_length=4096)


class MigrationConfirmation(BaseModel):
    candidate_token: str = Field(min_length=16, max_length=256)


class BackupSelection(BaseModel):
    backup_id: str = Field(pattern=r"^[0-9a-f]{24}$")


@lru_cache(maxsize=1)
def data_home_manager() -> DataHomeManager:
    if not settings.desktop_mode:
        raise RuntimeError("The desktop data-home API requires desktop mode")
    paths = DataHomePaths.from_trusted_environment()
    bundle = os.environ.get("PAYCHECK_MAP_DESKTOP_BUNDLE_ROOT")
    repository = (
        settings.project_root
        if paths.mode == "acceptance-synthetic-v1"
        and os.environ.get("PAYCHECK_MAP_DESKTOP_TEST_PROJECT_ROOT")
        else None
    )
    fail_at = os.environ.get("PAYCHECK_MAP_DATA_HOME_FAIL_AT")

    def failure_hook(phase: str) -> None:
        if fail_at == phase:
            from .data_home import InjectedFailure

            raise InjectedFailure(phase)

    return DataHomeManager(
        paths,
        migration_dir=settings.migration_dir,
        bundle_root=Path(bundle) if bundle else None,
        repository_root=repository,
        failure_hook=failure_hook if fail_at else None,
    )


def prepare_desktop_data_home() -> dict[str, Any]:
    return data_home_manager().prepare()


def _call[ResultT](action: Callable[..., ResultT], *args: Any, **kwargs: Any) -> ResultT:
    try:
        return action(*args, **kwargs)
    except DataHomeError as error:
        status = 409 if error.recoverable else 422
        raise HTTPException(
            status_code=status,
            detail={"code": error.code, "message": str(error)},
        ) from None


@router.get("/status")
def status() -> dict[str, Any]:
    return _call(data_home_manager().status)


@router.post("/fresh")
def fresh_setup() -> dict[str, Any]:
    return _call(data_home_manager().fresh_setup)


@router.post("/candidate")
def candidate(payload: CandidateSelection) -> dict[str, Any]:
    return _call(data_home_manager().inspect_candidate, Path(payload.selected_path))


@router.post("/migration")
def migrate(payload: MigrationConfirmation) -> dict[str, Any]:
    engine.dispose()
    return _call(data_home_manager().confirm_migration, payload.candidate_token)


@router.post("/backup")
def create_backup() -> dict[str, Any]:
    return _call(data_home_manager().create_backup)


@router.get("/backups")
def backups() -> dict[str, Any]:
    return {"backups": _call(data_home_manager().list_backups)}


@router.post("/restore-preview")
def restore_preview(payload: BackupSelection) -> dict[str, Any]:
    return _call(data_home_manager().preview_restore, payload.backup_id)


@router.post("/restore")
def restore(payload: BackupSelection) -> dict[str, Any]:
    engine.dispose()
    return _call(data_home_manager().confirm_restore, payload.backup_id)


@router.post("/resume")
def resume() -> dict[str, Any]:
    engine.dispose()
    return _call(data_home_manager().resume)


@router.post("/rollback")
def rollback() -> dict[str, Any]:
    engine.dispose()
    return _call(data_home_manager().rollback)


@router.get("/backups/{backup_id}/reveal")
def reveal_backup(backup_id: str) -> dict[str, Any]:
    path = _call(data_home_manager().backup_path, backup_id)
    return {"backup_id": backup_id, "filename": path.name, "approved": True}
