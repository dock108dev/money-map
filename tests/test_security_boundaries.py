from __future__ import annotations

import asyncio
import zipfile
from collections.abc import Iterator
from pathlib import Path

import anyio
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.types import Message

from paycheck_map.api_plaid import get_secret_store
from paycheck_map.app import app
from paycheck_map.config import Settings
from paycheck_map.db import get_session
from paycheck_map.desktop_app import DesktopSecurityMiddleware
from paycheck_map.import_security import ImportSecurityError, validate_import
from paycheck_map.keychain import MemorySecretStore
from paycheck_map.local_security import LocalSecurityMiddleware
from paycheck_map.refresh import refresh_guard
from paycheck_map.reporting import REPORT_FILENAME, _write_report


@pytest.mark.parametrize(
    "payload",
    [
        {"environment": "sandbox", "secret": "SYNTHETIC-SECRET-CANARY"},
        {"environment": {"SYNTHETIC-SECRET-CANARY": "value"}},
        {"environment": "SYNTHETIC-SECRET-CANARY"},
    ],
)
def test_rejected_request_never_reflects_secret_values(payload: object, session: Session) -> None:
    def sessions() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_secret_store] = MemorySecretStore

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
        ) as client:
            response = await client.post("/api/plaid/configuration", json=payload)
            assert response.status_code == 422
            assert "SYNTHETIC-SECRET-CANARY" not in response.text
            assert response.headers["cache-control"] == "no-store"

    try:
        anyio.run(exercise)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", "/api/plaid/configuration", {"environment": "sandbox"}),
        ("DELETE", "/api/plaid/configuration/sandbox", None),
        ("POST", "/api/plaid/link-token", {"target": "sofi"}),
        ("POST", "/api/plaid/exchange", {"session_id": "synthetic", "public_token": "synthetic"}),
        ("POST", "/api/plaid/connections/1/update-token", None),
        ("DELETE", "/api/plaid/connections/1", None),
    ],
)
def test_sensitive_connection_operations_cannot_race_refresh(
    method: str, path: str, payload: object, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Guarded operation reached a provider or credential prompt")

    monkeypatch.setattr("paycheck_map.native_secrets.request_plaid_credentials", forbidden)
    for name in [
        "configure_plaid",
        "clear_plaid_configuration",
        "create_plaid_link_session",
        "exchange_token_with_goal_observation",
        "create_plaid_update_session",
        "revoke_plaid_connection",
    ]:
        monkeypatch.setattr(f"paycheck_map.api_plaid.{name}", forbidden)

    def sessions() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_secret_store] = MemorySecretStore

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
        ) as client:
            with refresh_guard():
                response = await client.request(
                    method, path, json=payload, headers={"Content-Type": "application/json"}
                )
            assert response.status_code == 409

    try:
        anyio.run(exercise)
    finally:
        app.dependency_overrides.clear()
    with refresh_guard():
        pass


@pytest.mark.parametrize("module", ["local_security", "desktop_app"])
def test_slow_chunks_cannot_extend_total_body_deadline(
    module: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    middleware = (
        LocalSecurityMiddleware if module == "local_security" else DesktopSecurityMiddleware
    )
    monkeypatch.setattr(f"paycheck_map.{module}._BODY_READ_TIMEOUT_SECONDS", 0.03)

    async def receive() -> Message:
        await asyncio.sleep(0.01)
        return {"type": "http.request", "body": b"x", "more_body": True}

    async def exercise() -> None:
        assert await asyncio.wait_for(middleware._read_body(receive), timeout=0.2) is None

    anyio.run(exercise)


@pytest.mark.parametrize("middleware", [LocalSecurityMiddleware, DesktopSecurityMiddleware])
def test_empty_chunk_flood_is_bounded(
    middleware: type[LocalSecurityMiddleware] | type[DesktopSecurityMiddleware],
) -> None:
    count = 0

    async def receive() -> Message:
        nonlocal count
        count += 1
        return {"type": "http.request", "body": b"", "more_body": True}

    async def exercise() -> None:
        assert await middleware._read_body(receive) is None

    anyio.run(exercise)
    assert count == 1024


def test_desktop_rejects_ambiguous_content_type_and_transfer_encoding() -> None:
    for name in [b"content-type", b"transfer-encoding"]:
        assert not DesktopSecurityMiddleware._valid_security_headers(
            {b"host": [b"127.0.0.1:43123"], name: [b"a", b"b"]}
        )


@pytest.mark.parametrize("value", ["0.0.0.0", "localhost", "192.0.2.1", "::"])
def test_network_bind_configuration_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"host": value})


def test_standalone_private_directories_are_private_and_links_are_rejected(tmp_path: Path) -> None:
    settings = Settings(local_dir=tmp_path / "private")
    settings.ensure_private_dirs()
    for path in [
        settings.private_dir,
        settings.database_path.parent,
        settings.inbox_dir,
        settings.reports_dir,
        settings.backups_dir,
    ]:
        assert path.stat().st_mode & 0o777 == 0o700
    settings.inbox_dir.chmod(0o755)
    settings.ensure_private_dirs()
    assert settings.inbox_dir.stat().st_mode & 0o777 == 0o700
    settings.reports_dir.rmdir()
    target = tmp_path / "unrelated"
    target.mkdir()
    settings.reports_dir.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="rejected"):
        settings.ensure_private_dirs()


@pytest.mark.parametrize(
    "member,xml",
    [
        (
            "_rels/.rels",
            '<Relationships><Relationship TargetMode = "External" Target="https://example.invalid"/></Relationships>',
        ),
        (
            "_rels/.rels",
            '<r:Relationships xmlns:r="urn:test">'
            '<r:Relationship TargetMode="&#69;xternal"/></r:Relationships>',
        ),
        (
            "xl/worksheets/sheet1.xml",
            '<s:worksheet xmlns:s="urn:test"><s:f>1+1</s:f></s:worksheet>',
        ),
        ("xl/workbook.xml", '<!DOCTYPE root [<!ENTITY value "expanded">]><root>&value;</root>'),
    ],
)
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_workbook_policy_uses_xml_structure_not_byte_spelling(
    tmp_path: Path, member: str, xml: str, encoding: str
) -> None:
    path = tmp_path / "synthetic.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, xml.encode(encoding))
    with pytest.raises(ImportSecurityError):
        validate_import(path, approved_root=tmp_path)


@pytest.mark.parametrize(
    "content",
    [
        '{"a":1,"a":2}',
        '{"a":NaN}',
        '{"a":Infinity}',
        '{"a":1e999}',
        "[" * 1500 + "0" + "]" * 1500,
    ],
)
def test_ambiguous_or_excessively_nested_json_fails_safely(tmp_path: Path, content: str) -> None:
    path = tmp_path / "synthetic.json"
    path.write_text(content)
    with pytest.raises(ImportSecurityError):
        validate_import(path, approved_root=tmp_path)


def test_report_writer_ignores_preplaced_shared_temp_link(tmp_path: Path) -> None:
    settings = Settings(local_dir=tmp_path / "private")
    settings.ensure_private_dirs()
    untouched = tmp_path / "untouched"
    untouched.write_text("original")
    old_temp = settings.reports_dir / f".{REPORT_FILENAME}.tmp"
    old_temp.symlink_to(untouched)
    output = _write_report("<html>synthetic report</html>", settings)
    assert untouched.read_text() == "original"
    assert output.read_text() == "<html>synthetic report</html>"
    assert output.stat().st_mode & 0o777 == 0o600
    assert not list(settings.reports_dir.glob(".money-map-report-*.tmp"))
