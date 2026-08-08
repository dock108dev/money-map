from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn

from .config import settings
from .db import SessionLocal, initialize_database
from .ingestion import import_private_inbox, rollback_import_batch
from .payroll import generate_payroll_schedule, schedule_validation
from .reconciliation import reconcile_all
from .refresh import refresh_status, sync_all_connections
from .reporting import generate_trailing_report


def _run(command: list[str]) -> None:
    print(f"→ {' '.join(command)}")
    subprocess.run(command, cwd=settings.project_root, check=True)


def _frontend_needs_build() -> bool:
    index = settings.web_dist_dir / "index.html"
    if not index.exists():
        return True
    source_dir = settings.project_root / "web" / "src"
    if not source_dir.is_dir():
        return False
    source_times = [path.stat().st_mtime for path in source_dir.rglob("*") if path.is_file()]
    return bool(source_times and max(source_times) > index.stat().st_mtime)


def _build_frontend_if_needed() -> None:
    if not _frontend_needs_build():
        return
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError("pnpm is required to build the local frontend")
    _run([pnpm, "--dir", "web", "build"])


def _backup_database(label: str = "backup") -> Path:
    settings.ensure_private_dirs()
    if not settings.database_path.exists():
        initialize_database()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = settings.backups_dir / f"paycheck-map-{label}-{stamp}.sqlite3"
    with (
        sqlite3.connect(settings.database_path) as source,
        sqlite3.connect(destination) as target,
    ):
        source.backup(target)
    return destination


def _restore_database(source_path: Path) -> Path:
    source = source_path.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Backup does not exist: {source}")
    if source == settings.database_path.resolve():
        raise ValueError("Restore source must not be the active database")
    with sqlite3.connect(source) as check:
        result = check.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise ValueError("Backup failed SQLite integrity validation")
    safety_backup = _backup_database("pre-restore")
    temporary = settings.database_path.with_suffix(".restore.tmp")
    with (
        sqlite3.connect(source) as source_connection,
        sqlite3.connect(temporary) as target_connection,
    ):
        source_connection.backup(target_connection)
    temporary.replace(settings.database_path)
    return safety_backup


def _verify() -> None:
    python = sys.executable
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError("pnpm is required for verification")
    commands = [
        [python, "-m", "pytest"],
        [python, "-m", "ruff", "format", "--check", "."],
        [python, "-m", "ruff", "check", "."],
        [python, "-m", "mypy", "src", "tests"],
        [pnpm, "--dir", "web", "test"],
        [pnpm, "--dir", "web", "lint"],
        [pnpm, "--dir", "web", "build"],
        [python, "scripts/check_private_data.py"],
    ]
    for command in commands:
        _run(command)
    print("✓ Money Map verification passed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paycheck-map",
        description="Local-first paycheck allocation and forecasting",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="build and run the local application")
    serve.add_argument("--open", action="store_true", help="open the local URL in a browser")

    subparsers.add_parser("import", help="import the private local inbox")
    rollback = subparsers.add_parser("rollback", help="remove one import batch")
    rollback.add_argument("batch_id", type=int)
    subparsers.add_parser("report", help="generate the trailing-12-month local report")
    subparsers.add_parser("backup", help="back up the local SQLite database")
    restore = subparsers.add_parser("restore", help="restore an explicit SQLite backup")
    restore.add_argument("path", type=Path)
    subparsers.add_parser("payroll-regenerate", help="rebuild completed payroll history")
    subparsers.add_parser("payroll-status", help="validate completed payroll history")
    sync = subparsers.add_parser("sync", help="update all active read-only connections")
    sync.add_argument("--status", action="store_true", help="show whether data needs updating")
    subparsers.add_parser("verify", help="run the complete v1.2.1 release gate")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    settings.ensure_private_dirs()
    initialize_database()
    if arguments.command == "serve":
        _build_frontend_if_needed()
        url = f"http://{settings.host}:{settings.port}"
        if settings.host != "127.0.0.1":
            raise RuntimeError("Paycheck Map refuses to bind outside 127.0.0.1")
        print(f"Money Map is local-only: {url}")
        if arguments.open:
            webbrowser.open(url)
        uvicorn.run("paycheck_map.app:app", host=settings.host, port=settings.port, reload=False)
    elif arguments.command == "import":
        with SessionLocal() as session:
            outcome = import_private_inbox(session)
        print(
            f"Batch {outcome.batch_id}: {outcome.imported} imported, "
            f"{outcome.duplicates} duplicates, {len(outcome.errors)} errors"
        )
        for error in outcome.errors:
            print(f"  {error['filename']}: {error['message']}")
    elif arguments.command == "rollback":
        with SessionLocal() as session:
            if not rollback_import_batch(session, arguments.batch_id):
                raise SystemExit(f"Import batch {arguments.batch_id} was not found")
        print(f"Rolled back import batch {arguments.batch_id}")
    elif arguments.command == "report":
        with SessionLocal() as session:
            output = generate_trailing_report(session)
        print(f"Report saved locally: {output}")
    elif arguments.command == "backup":
        print(f"Backup saved locally: {_backup_database()}")
    elif arguments.command == "restore":
        safety_backup = _restore_database(arguments.path)
        print(f"Restore complete; previous database saved at {safety_backup}")
    elif arguments.command == "payroll-regenerate":
        with SessionLocal() as session:
            result = generate_payroll_schedule(session)
            reconcile_all(session)
            session.commit()
        print(
            f"Payroll complete: {result['rows']} rows "
            f"({result['statement_rows']} statements, {result['calculated_rows']} calculated)"
        )
    elif arguments.command == "payroll-status":
        with SessionLocal() as session:
            checks = schedule_validation(session)
        failed = [check for check in checks if check["status"] != "reconciled"]
        for check in checks:
            print(f"{check['status']}: {check['rule']}")
        if failed:
            raise SystemExit(f"{len(failed)} payroll validation check(s) failed")
        print(f"Payroll validation passed: {len(checks)} checks")
    elif arguments.command == "sync":
        with SessionLocal() as session:
            if arguments.status:
                status = refresh_status(session)
                latest = status["last_successful_refresh"] or "never"
                print(f"Latest successful refresh: {latest}")
                print(
                    f"Connections current: {status['connections_current']}/"
                    f"{status['active_connections']}"
                )
                print(f"Update needed today: {'yes' if status['refresh_needed'] else 'no'}")
                print(
                    "Connection attention needed: "
                    f"{'yes' if status['connections_needing_attention'] else 'no'}"
                )
            else:
                result = sync_all_connections(session)
                print(
                    f"Account update complete: {result['succeeded']} succeeded, "
                    f"{result['failed']} failed"
                )
                if result["failed"]:
                    raise SystemExit("One or more connections need attention")
    elif arguments.command == "verify":
        _verify()


if __name__ == "__main__":
    main()
