#!/usr/bin/env python3
"""Assemble a Fab source plugin from this checkout and a verified release payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "DccMcpUnreal"
PYTHON_ROOT = PurePosixPath("Content/Python")
DEPENDENCY_ROOT = PYTHON_ROOT / "Lib/site-packages"
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024


def checked_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > 20_000 or sum(item.file_size for item in members) > MAX_PAYLOAD_BYTES:
        raise ValueError("Release payload exceeds the submission size budget")
    seen: set[str] = set()
    for item in members:
        # ZipInfo normalizes backslashes and truncates NULs when reading on
        # Windows. Check the original member name before trusting that view.
        original = item.orig_filename
        path = PurePosixPath(item.filename)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in original
            or ":" in original
            or "\x00" in original
            or not path.parts
            or path.parts[0] != PLUGIN_NAME
            or item.flag_bits & 1
            or stat.S_ISLNK(item.external_attr >> 16)
        ):
            raise ValueError("Unsafe release member: {}".format(item.filename))
        identity = str(path).casefold()
        if identity in seen:
            raise ValueError("Duplicate release member: {}".format(item.filename))
        seen.add(identity)
    return members


def write_file(root: Path, relative: PurePosixPath, payload: bytes) -> None:
    target = root.joinpath(*relative.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def copy_source_tree(source: Path, target: Path) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Source symlinks are not supported: {}".format(path))
        if path.is_file() and not any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
            if path.suffix not in {".pyc", ".pyo"}:
                write_file(target, PurePosixPath(path.relative_to(source).as_posix()), path.read_bytes())


def validate_plugin(root: Path) -> dict:
    descriptor = json.loads((root / (PLUGIN_NAME + ".uplugin")).read_text(encoding="utf-8"))
    if not descriptor.get("Modules") or not list((root / "Source").rglob("*.Build.cs")):
        raise ValueError("Fab code plugins require a source code module")
    for directory in ("Config", "Content", "Resources", "Source"):
        if not (root / directory).is_dir():
            raise ValueError("Missing required plugin directory: {}".format(directory))
    required = [
        "Content/Python/init_unreal.py",
        "Content/Python/dcc_mcp_unreal/__init__.py",
        "Content/Python/Lib/site-packages/dcc_mcp_core/__init__.py",
        "Documentation/README.txt",
        "Documentation/ThirdPartyNotices.txt",
        "Documentation/License.txt",
    ]
    for name in required:
        if not (root / name).is_file():
            raise ValueError("Missing runtime or documentation: {}".format(name))
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(root)
        if any(part in {"Binaries", "Intermediate", "Saved", "__pycache__", "_plugin"} for part in relative.parts):
            raise ValueError("Unexpected generated or nested plugin content: {}".format(relative))
        if path.suffix.lower() in {".exe", ".lib", ".pyc", ".pyo"}:
            raise ValueError("Unexpected executable or build product: {}".format(relative))
        if path.suffix == ".py" and not relative.as_posix().startswith("Content/Python/"):
            raise ValueError("Python file outside Fab's permitted layout: {}".format(relative))
    return {"version": descriptor["VersionName"], "files": len(files), "code_modules": descriptor["Modules"]}


def build_submission(
    release_package: Path, expected_sha256: str, output_dir: Path, repo_root: Path = REPO_ROOT
) -> Path:
    expected_sha256 = expected_sha256.removeprefix("sha256:").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("An exact official release SHA-256 is required")
    actual = hashlib.sha256(release_package.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise ValueError("Release package SHA-256 mismatch")
    source_plugin = repo_root / "unreal/plugin"
    descriptor = json.loads((source_plugin / (PLUGIN_NAME + ".uplugin")).read_text(encoding="utf-8"))
    version = descriptor["VersionName"]
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ValueError("Invalid plugin version")
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "{}-{}-fab-source-win64.zip".format(PLUGIN_NAME, version)
    if destination.exists():
        raise FileExistsError("Refusing to replace an existing submission: {}".format(destination))
    with tempfile.TemporaryDirectory(prefix="fab-stage-", dir=str(output_dir)) as temporary:
        stage = Path(temporary) / PLUGIN_NAME
        for directory in ("Config", "Content", "Resources", "Source"):
            copy_source_tree(source_plugin / directory, stage / directory)
        copy_source_tree(repo_root / "src/dcc_mcp_unreal", stage / "Content/Python/dcc_mcp_unreal")
        with zipfile.ZipFile(release_package) as archive:
            members = checked_members(archive)
            upstream = json.loads(archive.read(PLUGIN_NAME + "/" + PLUGIN_NAME + ".uplugin"))
            if upstream.get("VersionName") != version:
                raise ValueError("Release payload and source plugin versions differ")
            licenses: list[bytes] = []
            for member in members:
                path = PurePosixPath(member.filename)
                if member.is_dir() or len(path.parts) < 4 or path.parts[1] != "python":
                    continue
                package = path.parts[2]
                if package != "dcc_mcp_core" and not package.startswith("dcc_mcp_core-"):
                    continue
                if path.name in {"direct_url.json", "RECORD", "INSTALLER", "REQUESTED"} or path.suffix in {
                    ".pyc",
                    ".pyo",
                }:
                    continue
                payload = archive.read(member)
                write_file(stage, DEPENDENCY_ROOT.joinpath(*path.parts[2:]), payload)
                if path.name.upper().startswith("LICENSE"):
                    licenses.append(payload)
            if not licenses:
                raise ValueError("The release payload is missing the dependency license")
        descriptor["Installed"] = False
        descriptor["SupportedTargetPlatforms"] = ["Win64"]
        descriptor.pop("EngineVersion", None)
        descriptor["Plugins"] = [
            {**entry, **({"Optional": False} if entry["Name"] == "PythonScriptPlugin" else {})}
            for entry in descriptor.get("Plugins", [])
        ]
        write_file(stage, PurePosixPath(PLUGIN_NAME + ".uplugin"), (json.dumps(descriptor, indent=4) + "\n").encode())
        filter_path = stage / "Config/FilterPlugin.ini"
        with filter_path.open("a", encoding="utf-8") as handle:
            handle.write("\n/Content/Python/...\n/Documentation/...\n")
        write_file(
            stage, PurePosixPath("Documentation/README.txt"), (repo_root / "packaging/fab/README.txt").read_bytes()
        )
        write_file(
            stage, PurePosixPath("Documentation/License.txt"), (repo_root / "packaging/fab/License.txt").read_bytes()
        )
        notices = b"DCC MCP Unreal: MIT license; source: https://github.com/dcc-mcp/dcc-mcp-unreal\n\n"
        notices += (
            b"dcc-mcp-core: MIT license; native Rust Python extension and Python package.\nSource: https://github.com/dcc-mcp/dcc-mcp-core\n\n"
            + b"\n\n".join(licenses)
        )
        write_file(stage, PurePosixPath("Documentation/ThirdPartyNotices.txt"), notices)
        report = validate_plugin(stage)
        report["files"] += 1  # Include the manifest written immediately below.
        report.update(
            {"release_sha256": actual, "source_release": "v" + version, "platform": "Win64", "layout": "fab-source"}
        )
        write_file(
            stage, PurePosixPath("Documentation/BuildManifest.json"), (json.dumps(report, indent=2) + "\n").encode()
        )
        staged_archive = Path(temporary) / "submission.zip"
        with zipfile.ZipFile(staged_archive, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    info = zipfile.ZipInfo(path.relative_to(stage.parent).as_posix(), (2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, path.read_bytes())
        # Stage on the destination filesystem, then publish a complete archive
        # atomically without replacing a submission created by another writer.
        os.link(staged_archive, destination)
    report["submission_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
    report["archive"] = destination.name
    destination.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-package", required=True, type=Path)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "dist/fab")
    args = parser.parse_args()
    print(build_submission(args.release_package, args.release_sha256, args.output_dir))


if __name__ == "__main__":
    main()
