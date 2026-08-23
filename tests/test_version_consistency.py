from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tomllib
from importlib.metadata import version as installed_version

import httpx

from paycheck_map import __product_version__, __version__
from paycheck_map.app import app

from .conftest import PROJECT_ROOT

PUBLIC_VERSION = "3.0.0-beta.1"
PYTHON_VERSION = "3.0.0b1"


def test_every_current_version_surface_agrees() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as project_file:
        project_version = tomllib.load(project_file)["project"]["version"]
    with (PROJECT_ROOT / "uv.lock").open("rb") as lock_file:
        locked_packages = tomllib.load(lock_file)["package"]
    locked_version = next(
        package["version"] for package in locked_packages if package["name"] == "paycheck-map"
    )
    frontend_version = json.loads(
        (PROJECT_ROOT / "web" / "package.json").read_text(encoding="utf-8")
    )["version"]
    tauri_version = json.loads(
        (PROJECT_ROOT / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )["version"]
    with (PROJECT_ROOT / "desktop/src-tauri/Cargo.toml").open("rb") as cargo_file:
        rust_version = tomllib.load(cargo_file)["package"]["version"]

    async def health_version() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test.local") as client:
            response = await client.get("/api/health")
        response.raise_for_status()
        return str(response.json()["version"])

    cli = subprocess.run(
        [sys.executable, "-m", "paycheck_map.cli", "--version"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert {
        "expected": PYTHON_VERSION,
        "python_package": __version__,
        "installed_metadata": installed_version("paycheck-map"),
        "pyproject": project_version,
        "uv_lock": locked_version,
    } == dict.fromkeys(
        [
            "expected",
            "python_package",
            "installed_metadata",
            "pyproject",
            "uv_lock",
        ],
        PYTHON_VERSION,
    )
    assert {
        "expected": PUBLIC_VERSION,
        "public_python_constant": __product_version__,
        "fastapi": app.version,
        "health": asyncio.run(health_version()),
        "cli": cli.stdout.strip().removeprefix("paycheck-map "),
        "frontend": frontend_version,
        "tauri": tauri_version,
        "rust": rust_version,
    } == dict.fromkeys(
        [
            "expected",
            "public_python_constant",
            "fastapi",
            "health",
            "cli",
            "frontend",
            "tauri",
            "rust",
        ],
        PUBLIC_VERSION,
    )
