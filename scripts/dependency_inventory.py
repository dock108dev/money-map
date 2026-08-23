from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command_json(command: list[str], cwd: Path) -> object:
    result = subprocess.run(command, cwd=cwd, capture_output=True, check=True, text=True)
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    uv = tomllib.loads((ROOT / "uv.lock").read_text())
    python_packages = []
    for package in uv["package"]:
        source = package.get("source", {})
        source_kind = next(iter(source), "unknown")
        if source_kind not in {"registry", "virtual", "editable"}:
            raise RuntimeError("Unapproved Python dependency source")
        python_packages.append(
            {"name": package["name"], "version": package["version"], "source": source_kind}
        )

    cargo = command_json(
        ["cargo", "metadata", "--locked", "--format-version", "1"],
        ROOT / "desktop/src-tauri",
    )
    rust_packages = []
    assert isinstance(cargo, dict)
    for package in cargo["packages"]:
        source = package["source"] or "workspace"
        if source != "workspace" and not source.startswith("registry+"):
            raise RuntimeError("Unapproved Rust dependency source")
        rust_packages.append(
            {"name": package["name"], "version": package["version"], "source": source}
        )

    pnpm = command_json(["pnpm", "list", "--prod", "--depth", "Infinity", "--json"], ROOT / "web")
    frontend: dict[tuple[str, str], dict[str, str]] = {}

    def collect(node: object) -> None:
        if not isinstance(node, dict):
            return
        for group in ("dependencies", "optionalDependencies"):
            values = node.get(group, {})
            if not isinstance(values, dict):
                continue
            for name, value in values.items():
                if not isinstance(value, dict) or "version" not in value:
                    continue
                version = str(value["version"])
                frontend[(str(name), version)] = {
                    "name": str(name),
                    "version": version,
                    "source": "npm-registry",
                }
                collect(value)

    collect(pnpm[0] if isinstance(pnpm, list) and pnpm else pnpm)
    inventory = {
        "contract": "money-map-sanitized-dependency-inventory-v1",
        "python": sorted(python_packages, key=lambda item: (item["name"], item["version"])),
        "rust": sorted(rust_packages, key=lambda item: (item["name"], item["version"])),
        "frontend_production": sorted(
            frontend.values(), key=lambda item: (item["name"], item["version"])
        ),
    }
    rendered = json.dumps(inventory, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
        return
    output = args.output.resolve()
    evidence_root = (ROOT / ".slice4-evidence").resolve()
    if output.parent != evidence_root:
        raise RuntimeError("Inventory output must use the ignored Slice 4 evidence root")
    evidence_root.mkdir(mode=0o700, exist_ok=True)
    output.write_text(rendered)
    output.chmod(0o600)
    print(
        f"Dependency inventory written: {len(python_packages)} Python, "
        f"{len(rust_packages)} Rust, {len(frontend)} frontend packages"
    )


if __name__ == "__main__":
    main()
