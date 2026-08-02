from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Local-only runtime paths and safe defaults."""

    model_config = SettingsConfigDict(env_prefix="PAYCHECK_MAP_")

    project_root: Path = Path(__file__).resolve().parents[2]
    local_dir: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8765

    @property
    def private_dir(self) -> Path:
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
    def migration_dir(self) -> Path:
        project_migrations = self.project_root / "alembic"
        if project_migrations.is_dir():
            return project_migrations
        return self.package_root / "_alembic"

    @property
    def web_dist_dir(self) -> Path:
        project_dist = self.project_root / "web" / "dist"
        if project_dist.is_dir():
            return project_dist
        return self.package_root / "web_dist"

    def ensure_private_dirs(self) -> None:
        for path in (
            self.inbox_dir,
            self.database_path.parent,
            self.reports_dir,
            self.backups_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
