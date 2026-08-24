from __future__ import annotations

import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .desktop_policy import uses_managed_data_home


class Settings(BaseSettings):
    """Local-only runtime paths and safe defaults."""

    model_config = SettingsConfigDict(env_prefix="PAYCHECK_MAP_")

    project_root: Path = Path(__file__).resolve().parents[2]
    local_dir: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    desktop_mode: bool = False
    desktop_data_mode: str | None = None
    desktop_app_root: Path | None = None
    desktop_cache_root: Path | None = None
    desktop_log_root: Path | None = None
    desktop_test_project_root: Path | None = None

    @property
    def private_dir(self) -> Path:
        if self.desktop_mode and uses_managed_data_home(self.desktop_data_mode):
            if self.desktop_app_root is None:
                raise RuntimeError("The trusted desktop application-data root is required")
            return self.desktop_app_root
        return self.local_dir or self.project_root / ".local"

    @property
    def inbox_dir(self) -> Path:
        return self.private_dir / "inbox"

    @property
    def database_path(self) -> Path:
        return self.private_dir / "data" / "paycheck-map.sqlite3"

    @property
    def reports_dir(self) -> Path:
        return self.private_dir / "reports"

    @property
    def backups_dir(self) -> Path:
        return self.private_dir / "backups"

    @property
    def package_root(self) -> Path:
        return Path(__file__).resolve().parent

    @property
    def runtime_root(self) -> Path:
        """Root for immutable packaged resources.

        Desktop mode intentionally has no repository fallback. PyInstaller places
        the packaged resources beside the frozen package under ``sys._MEIPASS``.
        """

        if self.desktop_mode:
            frozen_root = getattr(sys, "_MEIPASS", None)
            if frozen_root:
                return Path(frozen_root) / "paycheck_map"
            if self.desktop_test_project_root is not None:
                return self.desktop_test_project_root
            return self.package_root
        return self.project_root

    @property
    def migration_dir(self) -> Path:
        if self.desktop_mode:
            if self.desktop_test_project_root is not None:
                return self.runtime_root / "alembic"
            return self.runtime_root / "_alembic"
        project_migrations = self.project_root / "alembic"
        if project_migrations.is_dir():
            return project_migrations
        return self.package_root / "_alembic"

    @property
    def web_dist_dir(self) -> Path:
        if self.desktop_mode:
            if self.desktop_test_project_root is not None:
                return self.runtime_root / "web" / "dist"
            return self.runtime_root / "web_dist"
        project_dist = self.project_root / "web" / "dist"
        if project_dist.is_dir():
            return project_dist
        return self.package_root / "web_dist"

    @property
    def config_dir(self) -> Path:
        return self.runtime_root / "config"

    def ensure_private_dirs(self) -> None:
        for path in (
            self.inbox_dir,
            self.database_path.parent,
            self.reports_dir,
            self.backups_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
