from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import httpx
import pytest

from paycheck_map.config import Settings
from paycheck_map.keychain import MemorySecretStore


def test_runtime_inventory_is_complete_through_schema_head() -> None:
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / "desktop" / "runtime-resources.json").read_text())
    revisions = inventory["database"]["revisions"]
    assert revisions[-1] == "0009_goal_persistence"
    assert len(revisions) == 9
    assert {path.stem for path in (root / "alembic" / "versions").glob("*.py")} == set(revisions)
    modules = {
        ".".join(path.relative_to(root / "src").with_suffix("").parts)
        for path in (root / "src" / "paycheck_map").rglob("*.py")
    }
    assert set(inventory["python"]["modules"]) == modules
    assert (root / "web" / "dist" / "index.html").is_file()


def test_native_lifecycle_contract_is_bounded_and_cleans_up_children() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "desktop" / "src-tauri" / "src" / "main.rs").read_text()
    assert "recv_timeout(Duration::from_secs(30))" in source
    assert "Instant::now() + Duration::from_secs(45)" in source
    assert 'child.write(b"shutdown\\n")' in source
    assert "child.kill()" in source
    assert "RunEvent::Exit" in source


def test_sidecar_contract_uses_loopback_ephemeral_port_and_stdin_shutdown() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "paycheck_map" / "desktop_sidecar.py").read_text()
    assert 'listener.bind(("127.0.0.1", 0))' in source
    assert 'if line.strip() == "shutdown"' in source
    assert "server.should_exit = True" in source
    assert not re.search(r"\b8765\b", source)


def test_synthetic_keychain_namespace_is_isolated() -> None:
    store = MemorySecretStore()
    store.set("slice0-synthetic", "account", "synthetic-secret")
    assert store.get("slice0-synthetic", "account") == "synthetic-secret"
    assert store.get("plaid", "account") is None
    store.delete("slice0-synthetic", "account")
    assert store.get("slice0-synthetic", "account") is None


def test_desktop_resources_never_fall_back_to_repository(tmp_path: Path) -> None:
    project = tmp_path / "checkout"
    (project / "alembic").mkdir(parents=True)
    (project / "web" / "dist").mkdir(parents=True)
    packaged = Settings(
        project_root=project, local_dir=tmp_path / "money-map-slice0-data", desktop_mode=True
    )
    assert project not in packaged.migration_dir.parents
    assert project not in packaged.web_dist_dir.parents
    assert project not in packaged.config_dir.parents


def test_slice0_sidecar_rejects_non_disposable_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYCHECK_MAP_LOCAL_DIR", "/tmp/not-approved")
    from paycheck_map import desktop_sidecar

    with pytest.raises(RuntimeError, match="non-disposable"):
        desktop_sidecar._synthetic_root()


def test_desktop_auth_host_origin_and_redaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PAYCHECK_MAP_DESKTOP_SESSION", "synthetic-session-value")
    monkeypatch.setenv("PAYCHECK_MAP_DESKTOP_MODE", "true")
    monkeypatch.setenv("PAYCHECK_MAP_LOCAL_DIR", str(tmp_path / "money-map-slice0-auth"))
    import paycheck_map.desktop_app as module

    module = importlib.reload(module)
    transport = httpx.ASGITransport(app=module.desktop_app)

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:43123"
        ) as client:
            unauthorized = await client.get("/api/desktop/health")
            assert unauthorized.status_code == 401
            assert "synthetic-session-value" not in unauthorized.text
            trusted = await client.get(
                "/api/desktop/health",
                headers={
                    "X-Money-Map-Session": "synthetic-session-value",
                    "Origin": "http://tauri.localhost",
                },
            )
            assert trusted.status_code == 200
            assert trusted.json()["ready"] is True
            hostile = await client.get(
                "/api/desktop/health",
                headers={
                    "X-Money-Map-Session": "synthetic-session-value",
                    "Origin": "https://untrusted.invalid",
                },
            )
            assert hostile.status_code == 403
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:43123"
        ) as client:
            wrong_host = await client.get(
                "/api/desktop/health",
                headers={"X-Money-Map-Session": "synthetic-session-value"},
            )
            assert wrong_host.status_code == 400

    import anyio

    anyio.run(exercise)
