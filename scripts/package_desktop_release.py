#!/usr/bin/env python3
"""Build a sanitized, signed Money Map Slice 5 owner-machine candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.1.0"
SCHEMA = "0009_goal_persistence"
TARGET = "aarch64-apple-darwin"
TEAM = "E3G5D247ZN"
IDENTIFIER = "com.moneymap.desktop"
MINIMUM_MACOS = "13.0"
CONTRACT = "money-map-slice5-build-manifest-v1"
ARTIFACT_NAME = "Money Map-Slice5-arm64.dmg"
LOCKS = ("uv.lock", "web/pnpm-lock.yaml", "desktop/src-tauri/Cargo.lock")
REQUIRED_INPUTS = (
    *LOCKS,
    "pyproject.toml",
    "web/package.json",
    "desktop/src-tauri/Cargo.toml",
    "desktop/src-tauri/tauri.conf.json",
    "desktop/src-tauri/icons/icon.png",
    "desktop/src-tauri/icons/icon.svg",
    "desktop/runtime-resources.json",
    "scripts/build_signed_sidecar.py",
)
SECRET_ENV = re.compile(
    r"(^|_)(TOKEN|SECRET|PASSWORD|CREDENTIAL|ACCESS_KEY|PRIVATE_KEY)($|_)|"
    r"^(PLAID|AWS|AZURE|GCP|GH_|GITHUB_|OPENAI_|ANTHROPIC_|APPLE_)"
)
COMMAND_RESULTS: list[dict[str, object]] = []


def canary_args(canaries: list[str]) -> list[str]:
    return [part for canary in canaries for part in ("--canary", canary)]


def command_label(command: list[str]) -> str:
    executable = Path(command[0]).name
    if executable.startswith("python") and len(command) > 1 and command[1].endswith(".py"):
        return f"python:{Path(command[1]).name}"
    return executable


def sanitized_failure_detail(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    detail = " | ".join(lines[-8:]) if lines else "no diagnostic"
    detail = detail.replace(str(ROOT), "<repository>").replace(str(Path.home()), "<home>")
    detail = re.sub(r"/private/(?:tmp|var)/[^\s:\'\"]+", "<temporary-path>", detail)
    detail = re.sub(r"Apple Development:[^\n]+", "<Apple Development identity>", detail)
    return detail[:1000]


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    label = command_label(command)
    COMMAND_RESULTS.append({"command": label, "exit": result.returncode})
    if result.returncode:
        detail = sanitized_failure_detail(result.stderr)
        raise RuntimeError(f"{label} failed with exit status {result.returncode}: {detail}")
    return result.stdout.strip() if capture else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitized_env(identity: str, build_id: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not SECRET_ENV.search(key)}
    env.update(
        {
            "APPLE_SIGNING_IDENTITY": identity,
            "MONEY_MAP_BUILD_ID": build_id,
            "CARGO_NET_OFFLINE": "true",
            "SOURCE_DATE_EPOCH": "0",
            "TZ": "UTC",
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONHASHSEED": "0",
            "MONEY_MAP_ALLOW_ACCEPTANCE_HOME": "1",
        }
    )
    return env


def preflight(commit: str, identity: str) -> dict[str, object]:
    if run(["git", "branch", "--show-current"], capture=True) != "main":
        raise SystemExit("release packaging requires branch main")
    if run(["git", "rev-parse", "HEAD"], capture=True) != commit:
        raise SystemExit("HEAD does not equal the supplied source commit")
    if run(["git", "status", "--porcelain", "--untracked-files=all"], capture=True):
        raise SystemExit("release packaging requires a clean worktree")
    if run(["rustc", "--print", "host-tuple"], capture=True) != TARGET:
        raise SystemExit(f"release packaging requires {TARGET}")
    tracked = set(run(["git", "ls-files"], capture=True).splitlines())
    missing = [
        name for name in REQUIRED_INPUTS if name not in tracked or not (ROOT / name).is_file()
    ]
    if missing:
        raise SystemExit(f"missing tracked build inputs: {missing}")
    run(["uv", "lock", "--check"])
    run(["pnpm", "--dir", "web", "install", "--lockfile-only", "--offline", "--frozen-lockfile"])
    run(
        ["cargo", "metadata", "--locked", "--offline", "--format-version", "1"],
        cwd=ROOT / "desktop/src-tauri",
        capture=True,
    )
    config = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())
    cargo = (ROOT / "desktop/src-tauri/Cargo.toml").read_text()
    project = (ROOT / "pyproject.toml").read_text()
    migrations = sorted((ROOT / "alembic/versions").glob("*.py"))
    if (
        config["version"] != VERSION
        or f'version = "{VERSION}"' not in cargo
        or f'version = "{VERSION}"' not in project
    ):
        raise SystemExit("runtime version mismatch")
    if (
        not migrations
        or migrations[-1].name != f"{SCHEMA}.py"
        or any(p.name.startswith("0010") for p in migrations)
    ):
        raise SystemExit("schema mismatch or forbidden migration 0010")
    identities = run(["security", "find-identity", "-v", "-p", "codesigning"], capture=True)
    if identity not in identities:
        raise SystemExit("selected Apple Development identity is unavailable")
    certificate = run(["security", "find-certificate", "-c", identity, "-p"], capture=True)
    subject = subprocess.run(
        ["openssl", "x509", "-noout", "-subject"],
        input=certificate,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    if f"OU={TEAM}" not in subject.replace(" = ", "=") or "Apple Development" not in subject:
        raise SystemExit("selected signing identity has the wrong team or certificate class")
    return {
        "source_commit": commit,
        "clean_tree": True,
        "target": TARGET,
        "identity_class": "Apple Development",
        "signing_team": TEAM,
        "lockfile_hashes": {name: sha256(ROOT / name) for name in LOCKS},
        "input_hashes": {name: sha256(ROOT / name) for name in REQUIRED_INPUTS},
    }


def fresh_source(commit: str, root: Path) -> Path:
    source = root / "source"
    source.mkdir(mode=0o700)
    archive = root / "source.tar"
    run(["git", "archive", "--format=tar", "--output", str(archive), commit])
    run(["tar", "-xf", str(archive), "-C", str(source)])
    archive.unlink()
    return source


def macho_files(app: Path) -> list[Path]:
    found: list[Path] = []
    for path in app.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        result = subprocess.run(
            ["file", "-b", str(path)], capture_output=True, text=True, check=True
        )
        if "Mach-O" in result.stdout:
            found.append(path)
    return sorted(found, key=lambda p: (-len(p.parts), str(p)))


def sign_app(app: Path, identity: str) -> None:
    machos = macho_files(app)
    main = app / "Contents/MacOS/money-map-desktop"
    for path in machos:
        if path != main:
            run(["codesign", "--force", "--sign", identity, "--timestamp=none", str(path)])
    run(["codesign", "--force", "--sign", identity, "--timestamp=none", str(main)])
    run(["codesign", "--force", "--sign", identity, "--timestamp=none", str(app)])
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    run(
        [
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            f'-R=anchor apple generic and certificate leaf[subject.OU] = "{TEAM}"',
            str(app),
        ]
    )


def code_inventory(app: Path) -> list[dict[str, object]]:
    inventory = []
    for path in macho_files(app):
        details = run(
            [
                "codesign",
                "-d",
                "--verbose=4",
                "--requirements",
                "-",
                "--entitlements",
                ":-",
                str(path),
            ],
            capture=True,
        )
        architecture = run(["lipo", "-archs", str(path)], capture=True)
        if architecture.strip() != "arm64":
            raise SystemExit(f"non-thin-arm64 code: {path.relative_to(app)}")
        inventory.append(
            {
                "path": path.relative_to(app).as_posix(),
                "architecture": architecture,
                "sha256": sha256(path),
                "authority": "Apple Development",
                "team_identifier": TEAM,
                "designated_requirement": next(
                    (line for line in details.splitlines() if line.startswith("designated =>")),
                    "verified by codesign",
                ),
                "entitlements": [],
                "verification": "strict-pass",
            }
        )
    sidecar = app / "Contents/MacOS/money-map-sidecar"
    archive = CArchiveReader(str(sidecar))
    with tempfile.TemporaryDirectory(
        prefix="money-map-native-inventory.", dir="/private/tmp"
    ) as temp:
        temp_root = Path(temp)
        for index, name in enumerate(sorted(archive.toc)):
            extracted = archive.extract(name)
            if not isinstance(extracted, bytes) or extracted[:4] != bytes.fromhex("cffaedfe"):
                continue
            native = temp_root / f"native-{index}"
            native.write_bytes(extracted)
            architecture = run(["lipo", "-archs", str(native)], capture=True)
            if architecture != "arm64":
                raise SystemExit(f"non-thin-arm64 embedded code: {name}")
            run(
                [
                    "codesign",
                    "--verify",
                    "--strict",
                    f'-R=anchor apple generic and certificate leaf[subject.OU] = "{TEAM}"',
                    str(native),
                ]
            )
            inventory.append(
                {
                    "path": f"Contents/MacOS/money-map-sidecar::{name}",
                    "architecture": architecture,
                    "sha256": hashlib.sha256(extracted).hexdigest(),
                    "authority": "Apple Development",
                    "team_identifier": TEAM,
                    "designated_requirement": "verified by exact codesign team requirement",
                    "entitlements": [],
                    "verification": "strict-pass",
                }
            )
    return inventory


def validate_bundle(app: Path) -> None:
    plist = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    expected = {
        "CFBundleName": "Money Map",
        "CFBundleIdentifier": IDENTIFIER,
        "CFBundleShortVersionString": VERSION,
        "LSMinimumSystemVersion": MINIMUM_MACOS,
    }
    for key, value in expected.items():
        if plist.get(key) != value:
            raise SystemExit(f"bundle identity mismatch: {key}")
    if not (app / "Contents/Resources/icon.icns").is_file():
        raise SystemExit("app icon is missing")


def create_dmg(app: Path, dmg: Path, identity: str, build_root: Path) -> None:
    stage = build_root / "dmg-stage"
    stage.mkdir(mode=0o700)
    shutil.copytree(app, stage / "Money Map.app", copy_function=shutil.copy2)
    os.symlink("/Applications", stage / "Applications")
    temp_dmg = build_root / "candidate.dmg"
    run(
        [
            "hdiutil",
            "create",
            "-quiet",
            "-fs",
            "HFS+",
            "-volname",
            "Money Map",
            "-srcfolder",
            str(stage),
            "-format",
            "UDZO",
            str(temp_dmg),
        ]
    )
    shutil.copy2(temp_dmg, dmg)
    run(["codesign", "--force", "--sign", identity, "--timestamp=none", str(dmg)])
    run(["codesign", "--verify", "--strict", "--verbose=2", str(dmg)])


def verify_dmg(dmg: Path, evidence: Path, canaries: list[str]) -> list[str]:
    mount = Path(tempfile.mkdtemp(prefix="money-map-mount.", dir="/private/tmp"))
    try:
        run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(dmg)])
        entries = sorted(path.name for path in mount.iterdir() if path.name != ".DS_Store")
        if (
            entries != ["Applications", "Money Map.app"]
            or not (mount / "Applications").is_symlink()
        ):
            raise SystemExit(f"unexpected DMG layout: {entries}")
        mounted_app = mount / "Money Map.app"
        run(["codesign", "--verify", "--deep", "--strict", str(mounted_app)])
        run(
            [
                sys.executable,
                str(ROOT / "scripts/check_desktop_artifact.py"),
                str(mounted_app),
                *canary_args(canaries),
            ]
        )
        (evidence / "dmg-listing.json").write_text(json.dumps(entries, indent=2) + "\n")
        return entries
    finally:
        subprocess.run(
            ["hdiutil", "detach", str(mount)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(mount, ignore_errors=True)


def tool_versions(source: Path, env: dict[str, str]) -> dict[str, str]:
    commands = {
        "uv": ["uv", "--version"],
        "python": ["uv", "run", "--frozen", "python", "--version"],
        "pyinstaller": ["uv", "run", "--frozen", "pyinstaller", "--version"],
        "node": ["node", "--version"],
        "pnpm": ["pnpm", "--version"],
        "rustc": ["rustc", "--version"],
        "cargo": ["cargo", "--version"],
        "tauri": [str(source / "web/node_modules/.bin/tauri"), "--version"],
        "xcode": ["xcodebuild", "-version"],
    }
    return {
        name: run(command, cwd=source, env=env, capture=True).replace("\n", "; ")
        for name, command in commands.items()
    }


def build(args: argparse.Namespace) -> Path:
    COMMAND_RESULTS.clear()
    pre = preflight(args.commit, args.identity)
    evidence = ROOT / ".slice5-evidence" / args.build_id
    if evidence.exists():
        raise SystemExit("evidence/build ID already exists; refusing reuse")
    evidence.mkdir(parents=True, mode=0o700)
    build_root = Path(tempfile.mkdtemp(prefix=f"money-map-{args.build_id}.", dir="/private/tmp"))
    build_root.chmod(0o700)
    deterministic_build_id = f"slice5-{args.commit[:12]}"
    env = sanitized_env(args.identity, deterministic_build_id)
    try:
        source = fresh_source(args.commit, build_root)
        env["RUSTFLAGS"] = (
            f"--remap-path-prefix={Path.home() / '.cargo/registry'}=/cargo/registry "
            f"--remap-path-prefix={source}=/workspace"
        )
        run(
            ["pnpm", "--dir", "web", "install", "--offline", "--frozen-lockfile"],
            cwd=source,
            env=env,
        )
        run(
            [
                "/bin/zsh",
                str(source / "scripts/generate_macos_icons.sh"),
                str(source / "desktop/src-tauri/icons/icon.png"),
                str(source / "desktop/src-tauri/icons/icon.icns"),
            ],
            cwd=source,
            env=env,
        )
        run(["pnpm", "--dir", "web", "build"], cwd=source, env=env)
        run(["uv", "sync", "--frozen", "--offline"], cwd=source, env=env)
        runtime_data = build_root / "runtime-data"
        shutil.copytree(source / "alembic", runtime_data / "alembic")
        shutil.copytree(source / "config", runtime_data / "config")
        run(
            [
                "uv",
                "run",
                "--frozen",
                "python",
                "scripts/build_signed_sidecar.py",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--name",
                "money-map-sidecar",
                "--paths",
                "src",
                "--collect-submodules",
                "paycheck_map",
                "--collect-all",
                "keyring.backends",
                "--add-data",
                f"{runtime_data / 'alembic'}:paycheck_map/_alembic",
                "--add-data",
                f"{runtime_data / 'config'}:paycheck_map/config",
                "src/paycheck_map/desktop_sidecar.py",
            ],
            cwd=source,
            env=env,
        )
        binaries = source / "desktop/src-tauri/binaries"
        binaries.mkdir(parents=True)
        shutil.copy2(source / "dist/money-map-sidecar", binaries / f"money-map-sidecar-{TARGET}")
        run(
            [
                str(source / "web/node_modules/.bin/tauri"),
                "build",
                "--config",
                "desktop/src-tauri/tauri.conf.json",
                "--bundles",
                "app",
            ],
            cwd=source,
            env=env,
        )
        built_app = source / "desktop/src-tauri/target/release/bundle/macos/Money Map.app"
        app = evidence / "Money Map.app"
        shutil.copytree(built_app, app, copy_function=shutil.copy2)
        sign_app(app, args.identity)
        validate_bundle(app)
        canaries = args.canary
        run(
            [
                sys.executable,
                str(ROOT / "scripts/check_desktop_artifact.py"),
                str(app),
                *canary_args(canaries),
            ]
        )
        inventory = code_inventory(app)
        inventory_path = evidence / "nested-code.json"
        inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
        dependency_path = evidence / "dependencies.json"
        run(
            [
                sys.executable,
                str(source / "scripts/dependency_inventory.py"),
                "--output",
                str(dependency_path),
            ],
            cwd=source,
            env={**env, "MONEY_MAP_EVIDENCE_ROOT": str(evidence)},
        )
        dmg = evidence / ARTIFACT_NAME
        create_dmg(app, dmg, args.identity, build_root)
        verify_dmg(dmg, evidence, canaries)
        manifest = {
            "contract": CONTRACT,
            "source_commit": args.commit,
            "clean_tree": True,
            "runtime_version": VERSION,
            "schema_revision": SCHEMA,
            "bundle_identifier": IDENTIFIER,
            "target_architecture": TARGET,
            "minimum_macos": MINIMUM_MACOS,
            "build_id": deterministic_build_id,
            "evidence_id": args.build_id,
            "build_time_policy": "SOURCE_DATE_EPOCH=0; evidence recording UTC only",
            "recorded_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "packaging_command": (
                "uv run --frozen python scripts/package_desktop_release.py "
                f"{args.commit} --identity <Apple Development> --build-id {args.build_id}"
            ),
            "tools": tool_versions(source, env),
            "lockfile_hashes": pre["lockfile_hashes"],
            "approved_input_hashes": pre["input_hashes"],
            "signing": {
                "team": TEAM,
                "class": "Apple Development",
                "timestamp": "none",
                "hardened_runtime": False,
            },
            "app": {
                "path": "Money Map.app",
                "size": sum(p.stat().st_size for p in app.rglob("*") if p.is_file()),
                "sha256": signed_tree_digest(app),
                "sha256_tree": tree_digest(app),
            },
            "dmg": {"path": ARTIFACT_NAME, "size": dmg.stat().st_size, "sha256": sha256(dmg)},
            "nested_code_inventory": "nested-code.json",
            "entitlements": [],
            "dependency_inventory": {
                "path": "dependencies.json",
                "sha256": sha256(dependency_path),
            },
            "artifact_scan": "pass",
            "reproducibility": "pending comparison",
            "external_distribution_blocker": (
                "Developer ID Application identity, hardened runtime, notarization and "
                "stapling are unavailable/unperformed"
            ),
        }
        (evidence / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        (evidence / "commands.json").write_text(
            json.dumps(COMMAND_RESULTS, indent=2, sort_keys=True) + "\n"
        )
        privacy_scan(evidence, canaries)
        return evidence
    except BaseException:
        shutil.rmtree(evidence, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(build_root, ignore_errors=True)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        p for p in root.rglob("*") if p.is_file() and "_CodeSignature" not in p.parts
    ):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        file_type = run(["file", "-b", str(path)], capture=True)
        if path.name == "money-map-sidecar":
            file_hash = normalized_sidecar_digest(path)
        elif "Mach-O" in file_type:
            with tempfile.TemporaryDirectory(
                prefix="money-map-normalize.", dir="/private/tmp"
            ) as temp:
                unsigned = Path(temp) / path.name
                shutil.copy2(path, unsigned)
                subprocess.run(
                    ["codesign", "--remove-signature", str(unsigned)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                file_hash = sha256(unsigned)
        else:
            file_hash = sha256(path)
        digest.update(file_hash.encode() + b"\n")
    return digest.hexdigest()


def signed_tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(sha256(path).encode() + b"\n")
    return digest.hexdigest()


def normalized_sidecar_digest(sidecar: Path) -> str:
    digest = hashlib.sha256()
    with tempfile.TemporaryDirectory(
        prefix="money-map-sidecar-normalize.", dir="/private/tmp"
    ) as temp:
        temp_root = Path(temp)
        unsigned_sidecar = temp_root / "unsigned-sidecar"
        shutil.copy2(sidecar, unsigned_sidecar)
        subprocess.run(
            ["codesign", "--remove-signature", str(unsigned_sidecar)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        archive = CArchiveReader(str(unsigned_sidecar))
        with unsigned_sidecar.open("rb") as handle:
            bootloader = normalize_macho_container_metadata(handle.read(archive._start_offset))
        digest.update(hashlib.sha256(bootloader).hexdigest().encode() + b"\n")
        for index, name in enumerate(sorted(archive.toc)):
            extracted = archive.extract(name)
            if not isinstance(extracted, bytes):
                continue
            if extracted[:4] == bytes.fromhex("cffaedfe"):
                native = temp_root / f"native-{index}"
                native.write_bytes(extracted)
                subprocess.run(
                    ["codesign", "--remove-signature", str(native)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                content_hash = sha256(native)
            else:
                content_hash = hashlib.sha256(extracted).hexdigest()
            digest.update(name.encode() + b"\0" + content_hash.encode() + b"\n")
    return digest.hexdigest()


def normalize_macho_container_metadata(content: bytes) -> bytes:
    normalized = bytearray(content)
    if normalized[:4] != bytes.fromhex("cffaedfe"):
        raise ValueError("expected a thin arm64 Mach-O bootloader")
    command_count = struct.unpack_from("<I", normalized, 16)[0]
    offset = 32
    for _ in range(command_count):
        command, size = struct.unpack_from("<II", normalized, offset)
        if size < 8 or offset + size > len(normalized):
            raise ValueError("invalid Mach-O load command")
        if command == 0x19 and normalized[offset + 8 : offset + 24].rstrip(b"\0") == b"__LINKEDIT":
            normalized[offset + 32 : offset + 40] = b"\0" * 8
            normalized[offset + 48 : offset + 56] = b"\0" * 8
        elif command == 0x2:
            normalized[offset + 20 : offset + 24] = b"\0" * 4
        elif command == 0x1B:
            normalized[offset + 8 : offset + 24] = b"\0" * 16
        offset += size
    return bytes(normalized)


def privacy_scan(root: Path, canaries: list[str]) -> None:
    forbidden = [str(ROOT), str(ROOT.parent), "/private/tmp/", *canaries]
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            lowered = path.name.lower()
            if lowered.endswith((".db", ".sqlite", ".sqlite3", ".map", ".dSYM".lower())):
                raise SystemExit(f"forbidden evidence/artifact file: {path.name}")
            data = path.read_bytes()
            if any(marker.encode() in data for marker in forbidden if marker):
                raise SystemExit(f"private/build path or canary in evidence: {path.name}")


def compare(build_a: Path, build_b: Path, output: Path) -> None:
    a = json.loads((build_a / "manifest.json").read_text())
    b = json.loads((build_b / "manifest.json").read_text())
    functional_fields = (
        "source_commit",
        "runtime_version",
        "schema_revision",
        "bundle_identifier",
        "target_architecture",
        "minimum_macos",
        "lockfile_hashes",
        "approved_input_hashes",
        "entitlements",
    )
    functional = all(a[field] == b[field] for field in functional_fields)
    payload = a["app"]["sha256_tree"] == b["app"]["sha256_tree"]
    app_a = build_a / "Money Map.app"
    app_b = build_b / "Money Map.app"
    signed_file_differences: list[str] = []
    if app_a.is_dir() and app_b.is_dir():
        relative_files = sorted(
            {path.relative_to(app_a) for path in app_a.rglob("*") if path.is_file()}
            | {path.relative_to(app_b) for path in app_b.rglob("*") if path.is_file()}
        )
        signed_file_differences = [
            relative.as_posix()
            for relative in relative_files
            if not (app_a / relative).is_file()
            or not (app_b / relative).is_file()
            or sha256(app_a / relative) != sha256(app_b / relative)
        ]
    report = {
        "contract": "money-map-slice5-reproducibility-v1",
        "functional_identity": functional,
        "normalized_unsigned_payload_identity": payload,
        "signed_app_byte_identity": a["app"]["sha256"] == b["app"]["sha256"],
        "signed_dmg_byte_identity": a["dmg"]["sha256"] == b["dmg"]["sha256"],
        "signed_app_differing_files": signed_file_differences,
        "signed_dmg_differing_fields": ["size", "sha256"],
        "expected_differences": [
            "Apple code-signing CodeResources and CMS signatures",
            "HFS+ DMG container identifiers and filesystem metadata",
        ],
        "unexplained_payload_differences": []
        if payload
        else ["normalized app payload digest differs"],
    }
    if not functional or not payload:
        raise SystemExit("reproducibility comparison failed")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for build_root, manifest in ((build_a, a), (build_b, b)):
        manifest["reproducibility"] = {
            "result": "pass",
            "comparison": output.name,
            "normalized_unsigned_payload_identity": True,
        }
        (build_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("commit", nargs="?")
    parser.add_argument("--identity")
    parser.add_argument("--build-id")
    parser.add_argument("--canary", action="append", default=[])
    parser.add_argument("--compare", nargs=2, metavar=("BUILD_A", "BUILD_B"), type=Path)
    parser.add_argument("--comparison-output", type=Path)
    args = parser.parse_args()
    if args.compare:
        if not args.comparison_output:
            parser.error("--comparison-output is required with --compare")
        compare(args.compare[0], args.compare[1], args.comparison_output)
        return
    if not args.commit or not args.identity or not args.build_id:
        parser.error("commit, --identity and --build-id are required")
    try:
        evidence = build(args)
    except KeyboardInterrupt:
        raise SystemExit("Slice 5 packaging aborted; incomplete output removed") from None
    except Exception as error:
        raise SystemExit(f"Slice 5 packaging failed: {error}") from None
    print(f"Slice 5 candidate complete: {evidence.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
