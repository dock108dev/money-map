from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path

import anyio
import pytest
from starlette.types import Message, Scope

from paycheck_map.data_home import DataHomeError, _write_metadata_digest
from paycheck_map.desktop_bootstrap import clear_bootstrap, install_bootstrap
from paycheck_map.import_security import LIMITS, ImportSecurityError, validate_import
from paycheck_map.keychain import MacOSKeychainSecretStore, SecretStoreError
from paycheck_map.native_secrets import request_plaid_credentials
from paycheck_map.safe_events import SafeEventLog

from .test_data_home import _manager

ROOT = Path(__file__).resolve().parents[1]


def test_tauri_capabilities_equal_the_registered_application_commands() -> None:
    build = (ROOT / "desktop/src-tauri/build.rs").read_text()
    main_source = (ROOT / "desktop/src-tauri/src/main.rs").read_text()
    commands = set(re.findall(r'"(desktop_[a-z_]+)"', build))
    registered_match = re.search(
        r"tauri::generate_handler!\[(.*?)\]\)", main_source, flags=re.DOTALL
    )
    assert registered_match is not None
    registered = set(re.findall(r"\b(desktop_[a-z_]+)\b", registered_match.group(1)))
    assert commands == registered

    config = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())
    main = json.loads((ROOT / "desktop/src-tauri/capabilities/default.json").read_text())
    safe = json.loads((ROOT / "desktop/src-tauri/capabilities/safe-error.json").read_text())
    assert config["app"]["security"]["capabilities"] == [
        "main-window",
        "safe-error-window",
    ]
    assert set(main["permissions"]) == {
        f"allow-{command.replace('_', '-')}" for command in commands
    }
    assert main["windows"] == ["main"]
    assert safe["windows"] == ["safe-error"]
    assert set(safe["permissions"]) == {
        "allow-desktop-runtime-status",
        "allow-desktop-restart",
        "allow-desktop-about",
    }
    encoded = json.dumps([main, safe])
    for forbidden in ('"*"', "shell:", "fs:", "http:", "opener:", "core:default"):
        assert forbidden not in encoded


def test_csp_is_explicit_and_contains_no_wildcards_or_unsafe_eval() -> None:
    config = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())
    csp = config["app"]["security"]["csp"]
    directives = {part.strip().split(" ", 1)[0] for part in csp.split(";") if part.strip()}
    assert directives == {
        "default-src",
        "script-src",
        "style-src",
        "img-src",
        "font-src",
        "frame-src",
        "connect-src",
        "object-src",
        "base-uri",
        "form-action",
        "frame-ancestors",
        "worker-src",
        "media-src",
    }
    assert "*" not in csp
    assert "unsafe-eval" not in csp
    assert "http://127.0.0.1" not in csp
    assert "https://cdn.plaid.com" in csp
    assert "https://sandbox.plaid.com" in csp
    assert "https://production.plaid.com" in csp


def test_private_bootstrap_is_bounded_single_use_and_not_environment_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paycheck_map.desktop_sidecar import _read_bootstrap

    read_fd, write_fd = os.pipe()
    monkeypatch.setenv("PAYCHECK_MAP_DESKTOP_BOOTSTRAP_FD", str(read_fd))
    os.write(
        write_fd,
        b'{"attestation":null,"candidate_artifact":"synthetic","candidate_commit":"b51465476d4cd628ff58553df466c200a1ac565e","contract":"money-map-desktop-bootstrap-v1","session":"'
        + b"a" * 64
        + b'"}\n',
    )
    os.close(write_fd)
    assert _read_bootstrap() == {
        "session": "a" * 64,
        "attestation": None,
        "candidate_commit": "b51465476d4cd628ff58553df466c200a1ac565e",
        "candidate_artifact": "synthetic",
    }
    assert "PAYCHECK_MAP_DESKTOP_BOOTSTRAP_FD" not in os.environ
    assert "PAYCHECK_MAP_DESKTOP_SESSION" not in os.environ
    with pytest.raises(RuntimeError, match="unavailable"):
        _read_bootstrap()


def test_private_control_descriptor_is_bounded_single_use_and_not_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paycheck_map.desktop_sidecar import _control_handle

    read_fd, write_fd = os.pipe()
    monkeypatch.setenv("PAYCHECK_MAP_DESKTOP_CONTROL_FD", str(read_fd))
    with _control_handle() as control:
        os.write(
            write_fd,
            b'{"command":"shutdown","contract":"money-map-control-v1"}\n',
        )
        os.close(write_fd)
        assert control.readline().strip() == (
            '{"command":"shutdown","contract":"money-map-control-v1"}'
        )
    assert "PAYCHECK_MAP_DESKTOP_CONTROL_FD" not in os.environ
    with pytest.raises(RuntimeError, match="unavailable"):
        _control_handle()


def test_desktop_owner_pid_is_bounded_and_removed_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paycheck_map.desktop_sidecar import _owner_is_alive, _owner_pid

    monkeypatch.setenv("PAYCHECK_MAP_DESKTOP_OWNER_PID", str(os.getpid()))
    assert _owner_pid() == os.getpid()
    assert "PAYCHECK_MAP_DESKTOP_OWNER_PID" not in os.environ
    assert _owner_is_alive(os.getpid())
    monkeypatch.setenv("PAYCHECK_MAP_DESKTOP_OWNER_PID", "1")
    with pytest.raises(RuntimeError, match="unavailable"):
        _owner_pid()


def _security_request(
    headers: list[tuple[bytes, bytes]], *, method: str = "GET", path: str = "/api/desktop/health"
) -> list[Message]:
    from paycheck_map.desktop_app import DesktopSecurityMiddleware

    messages: list[Message] = []
    received = False

    async def receive() -> Message:
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    async def inner(*_: object) -> None:
        raise AssertionError("Rejected request reached the financial application")

    scope: Scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "server": ("127.0.0.1", 43123),
        "client": ("127.0.0.1", 50000),
    }
    middleware = DesktopSecurityMiddleware(inner)

    async def exercise() -> None:
        await middleware(scope, receive, send)

    anyio.run(exercise)
    return messages


@pytest.mark.parametrize(
    "headers",
    [
        [(b"host", b"127.0.0.1:43123")],
        [(b"host", b"127.0.0.1:43123"), (b"host", b"127.0.0.1:43123")],
        [
            (b"host", b"127.0.0.1:43123"),
            (b"x-money-map-session", b"a" * 64),
            (b"x-money-map-session", b"a" * 64),
        ],
        [
            (b"host", b"127.0.0.1:43123"),
            (b"x-money-map-session", b"a" * 64),
            (b"origin", b"tauri://localhost"),
            (b"origin", b"tauri://localhost"),
        ],
        [
            (b"host", b"127.0.0.1:43123"),
            (b"x-money-map-session", b"a" * 64),
            (b"content-length", b"0"),
            (b"transfer-encoding", b"chunked"),
        ],
        [(b"host", b"127.0.0.1:9"), (b"x-money-map-session", b"a" * 64)],
        [
            (b"host", b"127.0.0.1:43123"),
            (b"x-money-map-session", b"a" * 64),
            (b"origin", b"https://evil.invalid"),
        ],
    ],
)
def test_duplicate_ambiguous_and_hostile_security_headers_fail_closed(
    headers: list[tuple[bytes, bytes]],
) -> None:
    clear_bootstrap()
    install_bootstrap("a" * 64, 43123)
    messages = _security_request(headers)
    assert messages[0]["status"] in {400, 401, 403}
    body = messages[-1].get("body", b"")
    assert isinstance(body, bytes)
    assert b"a" * 64 not in body
    clear_bootstrap()


def test_previous_generation_session_is_rejected_after_rotation() -> None:
    clear_bootstrap()
    install_bootstrap("b" * 64, 43123)
    messages = _security_request(
        [
            (b"host", b"127.0.0.1:43123"),
            (b"x-money-map-session", b"a" * 64),
            (b"origin", b"tauri://localhost"),
        ]
    )
    assert messages[0]["status"] == 401
    clear_bootstrap()


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_hostile_import_container_matrix_is_bounded(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    cases: list[Path] = []

    empty = inbox / "empty.csv"
    empty.touch()
    cases.append(empty)
    wrong_signature = inbox / "wrong.pdf"
    wrong_signature.write_bytes(b"not a pdf")
    cases.append(wrong_signature)
    formula = inbox / "formula.csv"
    formula.write_text(
        "institution,account,date,record_type,role,amount\n=CMD,x,2026-01-01,transaction,fee,1\n"
    )
    cases.append(formula)
    traversal = inbox / "traversal.xlsx"
    _write_zip(traversal, {"../escape.xml": b"x"})
    cases.append(traversal)
    external = inbox / "external.xlsx"
    _write_zip(external, {"xl/_rels/workbook.xml.rels": b'<Relationship TargetMode="External"/>'})
    cases.append(external)
    formula_xlsx = inbox / "formula.xlsx"
    _write_zip(formula_xlsx, {"xl/worksheets/sheet1.xml": b"<worksheet><f>1+1</f></worksheet>"})
    cases.append(formula_xlsx)
    active_pdf = inbox / "active.pdf"
    active_pdf.write_bytes(b"%PDF-1.7\n/OpenAction /JavaScript\n%%EOF")
    cases.append(active_pdf)
    unicode_name = inbox / "fullwidth\uff0dname.csv"
    unicode_name.write_text("a,b\n1,2\n")
    cases.append(unicode_name)
    symlink = inbox / "linked.csv"
    symlink.symlink_to(formula)
    cases.append(symlink)
    hardlink = inbox / "hardlinked.csv"
    hardlink.hardlink_to(formula)
    cases.append(hardlink)
    fifo = inbox / "pipe.csv"
    os.mkfifo(fifo)
    cases.append(fifo)
    directory = inbox / "directory.csv"
    directory.mkdir()
    cases.append(directory)

    for path in cases:
        with pytest.raises(ImportSecurityError):
            validate_import(path, approved_root=inbox)

    outside = tmp_path / "outside.csv"
    outside.write_text("a,b\n1,2\n")
    with pytest.raises(ImportSecurityError, match="location"):
        validate_import(outside, approved_root=inbox)

    oversized = inbox / "oversized.csv"
    with oversized.open("wb") as handle:
        handle.truncate(LIMITS.max_file_bytes + 1)
    with pytest.raises(ImportSecurityError, match="size"):
        validate_import(oversized, approved_root=inbox)


def test_catalog_journal_backup_and_confirmation_tampering_fail_closed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.fresh_setup()
    backup = manager.create_backup()
    preview = manager.preview_restore(backup["backup_id"])
    with pytest.raises(DataHomeError, match="Preview"):
        manager.confirm_restore(backup["backup_id"], "x" * 43)

    preview = manager.preview_restore(backup["backup_id"])
    manager.paths.backup_catalog.write_text("{}")
    with pytest.raises(DataHomeError, match="metadata"):
        manager.confirm_restore(backup["backup_id"], preview["confirmation_token"])

    manager = _manager(tmp_path / "journal")
    manager.fresh_setup()
    journal = json.loads(manager.paths.journal.read_text())
    journal["attacker_field"] = "rejected"
    manager.paths.journal.write_text(json.dumps(journal))
    _write_metadata_digest(manager.paths.journal, manager.paths.journal_digest)
    with pytest.raises(DataHomeError, match="Recovery information"):
        manager.prepare()

    manager = _manager(tmp_path / "backup")
    manager.fresh_setup()
    backup = manager.create_backup()
    path = manager.backup_path(backup["backup_id"])
    path.write_bytes(path.read_bytes()[:-32])
    with pytest.raises(DataHomeError):
        manager.backup_path(backup["backup_id"])


def test_keychain_contract_is_versioned_exact_and_deletes_synthetic_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "keyring.get_password", lambda service, account: values.get((service, account))
    )
    monkeypatch.setattr(
        "keyring.set_password",
        lambda service, account, value: values.__setitem__((service, account), value),
    )

    def delete(service: str, account: str) -> None:
        values.pop((service, account), None)

    monkeypatch.setattr("keyring.delete_password", delete)
    store = MacOSKeychainSecretStore()
    store.set("slice4.acceptance", "slice4.synthetic-item", "canary-value")
    assert store.get("slice4.acceptance", "slice4.synthetic-item") == "canary-value"
    assert set(values) == {
        ("com.moneymap.desktop.secrets.v1.slice4.acceptance", "slice4.synthetic-item")
    }
    store.delete("slice4.acceptance", "slice4.synthetic-item")
    assert values == {}
    with pytest.raises(SecretStoreError):
        store.set("plaid.items", "../../owner", "secret")
    with pytest.raises(SecretStoreError):
        store.get("unknown", "item")


def test_safe_event_log_has_fixed_schema_permissions_rotation_and_no_canary(tmp_path: Path) -> None:
    log = SafeEventLog(tmp_path / "logs")
    log.emit("MM-DESKTOP-START", "lifecycle")
    path = tmp_path / "logs" / "desktop-events.jsonl"
    payload = json.loads(path.read_text())
    assert set(payload) == {"contract", "code", "classification", "at"}
    assert "CANARY-PRIVATE-DESCRIPTION" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="Unsafe"):
        log.emit("CANARY-PRIVATE-DESCRIPTION", "lifecycle")


def test_native_secret_prompt_uses_a_fixed_process_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    values = iter(["client-id-value\n", "secret-value\n"])

    class Result:
        returncode = 0
        stderr = ""

        def __init__(self) -> None:
            self.stdout = next(values)

    def fake_run(args: list[str], **kwargs: object) -> Result:
        calls.append(args)
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
        return Result()

    monkeypatch.setattr("paycheck_map.native_secrets.sys.platform", "darwin")
    monkeypatch.setattr("paycheck_map.native_secrets.subprocess.run", fake_run)
    assert request_plaid_credentials() == ("client-id-value", "secret-value")
    assert all(call[:2] == ["/usr/bin/osascript", "-e"] for call in calls)
    assert "client-id-value" not in repr(calls)
    assert "secret-value" not in repr(calls)
