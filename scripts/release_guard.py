#!/usr/bin/env python3
"""Fail-closed release identity, archive, and asset no-clobber checks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional

VERSION_FILES = (
    ".release-please-manifest.json",
    "pyproject.toml",
    "src/dcc_mcp_unreal/__version__.py",
    "unreal/plugin/DccMcpUnreal.uplugin",
)
TAG_PATTERN = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class ReleaseGuardError(RuntimeError):
    """A release identity or immutability contract was not satisfied."""


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise ReleaseGuardError(diagnostic)
    return completed.stdout.strip()


def _canonical_tag(tag: str) -> str:
    if TAG_PATTERN.fullmatch(tag) is None:
        raise ReleaseGuardError("tag must be a canonical vMAJOR.MINOR.PATCH value")
    return tag


def _canonical_sha(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if SHA_PATTERN.fullmatch(normalized) is None:
        raise ReleaseGuardError("{} must be an exact 40-character commit SHA".format(field))
    return normalized


def _parse_version_documents(documents: Dict[str, str]) -> str:
    manifest = json.loads(documents[VERSION_FILES[0]])
    manifest_version = manifest.get(".") if isinstance(manifest, dict) else None

    project_text = documents[VERSION_FILES[1]]
    project_section = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", project_text)
    project_match = re.search(
        r'^version\s*=\s*["\']([0-9]+\.[0-9]+\.[0-9]+)["\']\s*$',
        project_section.group(1) if project_section else "",
        re.MULTILINE,
    )
    module_match = re.search(
        r'^__version__\s*=\s*["\']([0-9]+\.[0-9]+\.[0-9]+)["\']',
        documents[VERSION_FILES[2]],
        re.MULTILINE,
    )
    descriptor = json.loads(documents[VERSION_FILES[3]])
    descriptor_version = descriptor.get("VersionName") if isinstance(descriptor, dict) else None
    versions = {
        "manifest": manifest_version,
        "pyproject": project_match.group(1) if project_match else None,
        "module": module_match.group(1) if module_match else None,
        "plugin": descriptor_version,
    }
    unique = set(versions.values())
    if None in unique or len(unique) != 1:
        raise ReleaseGuardError("embedded release versions disagree: {}".format(json.dumps(versions, sort_keys=True)))
    version = str(next(iter(unique)))
    if TAG_PATTERN.fullmatch("v" + version) is None:
        raise ReleaseGuardError("embedded release version is not canonical")
    return version


def _version_at_commit(repo: Path, commit: str) -> str:
    documents = {path: _git(repo, "show", "{}:{}".format(commit, path)) for path in VERSION_FILES}
    return _parse_version_documents(documents)


def _version_in_checkout(repo: Path) -> str:
    documents = {path: (repo / path).read_text(encoding="utf-8") for path in VERSION_FILES}
    return _parse_version_documents(documents)


def resolve_source(repo: Path, tag: str, event_sha: str) -> Dict[str, object]:
    event_sha = _canonical_sha(event_sha, "event_sha")
    _git(repo, "cat-file", "-e", "{}^{{commit}}".format(event_sha))
    if tag:
        tag = _canonical_tag(tag)
        source_sha = _canonical_sha(
            _git(repo, "rev-parse", "--verify", "refs/tags/{}^{{commit}}".format(tag)), "tag source"
        )
        version = _version_at_commit(repo, source_sha)
        if tag != "v" + version:
            raise ReleaseGuardError("tag and embedded version do not match")
        return {
            "mode": "recovery",
            "publish_pypi": False,
            "source_sha": source_sha,
            "tag_name": tag,
            "version": version,
        }

    source_sha = event_sha
    version = _version_at_commit(repo, source_sha)
    subject = _git(repo, "show", "-s", "--format=%s", source_sha)
    is_release = subject in {
        "chore: release {}".format(version),
        "chore(main): release {}".format(version),
    }
    return {
        "mode": "release" if is_release else "idle",
        "publish_pypi": is_release,
        "source_sha": source_sha,
        "tag_name": "v" + version if is_release else "",
        "version": version,
    }


def verify_source(repo: Path, tag: str, expected_sha: str, require_tag: bool = False) -> Dict[str, object]:
    tag = _canonical_tag(tag)
    expected_sha = _canonical_sha(expected_sha, "expected_sha")
    head = _canonical_sha(_git(repo, "rev-parse", "HEAD"), "checked out source")
    if head != expected_sha:
        raise ReleaseGuardError("checkout is not the exact source commit")
    tag_exists = (
        subprocess.run(
            ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", "refs/tags/{}".format(tag)],
            check=False,
        ).returncode
        == 0
    )
    if require_tag and not tag_exists:
        raise ReleaseGuardError("required tag is missing from the release checkout")
    if tag_exists:
        tagged = _canonical_sha(
            _git(repo, "rev-parse", "--verify", "refs/tags/{}^{{commit}}".format(tag)), "tag source"
        )
        if tagged != expected_sha:
            raise ReleaseGuardError("tag does not resolve to the exact source commit")
    version = _version_in_checkout(repo)
    if tag != "v" + version:
        raise ReleaseGuardError("tag and embedded version do not match")
    return {"source_sha": head, "tag_name": tag, "version": version}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _flat_files(root: Path) -> Dict[str, Path]:
    if not root.is_dir():
        raise ReleaseGuardError("asset directory does not exist: {}".format(root))
    files: Dict[str, Path] = {}
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if path.is_symlink():
            raise ReleaseGuardError("release assets must not be symbolic links")
        if path.name in files:
            raise ReleaseGuardError("asset names must be unique: {}".format(path.name))
        files[path.name] = path
    return files


def plan_assets(local_dir: Path, existing_dir: Path) -> Dict[str, List[str]]:
    local = _flat_files(local_dir)
    existing = _flat_files(existing_dir)
    unexpected = sorted(set(existing) - set(local))
    if unexpected:
        raise ReleaseGuardError("existing release has unexpected assets: {}".format(", ".join(unexpected)))
    retain: List[str] = []
    upload: List[str] = []
    for name, local_path in local.items():
        existing_path = existing.get(name)
        if existing_path is None:
            upload.append(name)
        elif _sha256(local_path) == _sha256(existing_path):
            retain.append(name)
        else:
            raise ReleaseGuardError("existing asset {} has different bytes".format(name))
    return {"retain": sorted(retain), "upload": sorted(upload)}


def plan_pypi(
    dist_dir: Path,
    project: str,
    version: str,
    metadata_file: Optional[Path] = None,
    require_existing: bool = False,
) -> Dict[str, object]:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", project) is None:
        raise ReleaseGuardError("PyPI project name is not canonical")
    if TAG_PATTERN.fullmatch("v" + version) is None:
        raise ReleaseGuardError("PyPI version is not canonical")
    local = _flat_files(dist_dir)
    if not local or any(not name.endswith((".whl", ".tar.gz")) for name in local):
        raise ReleaseGuardError("Python distributions must contain only wheel and sdist files")
    if metadata_file is not None:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    else:
        url = "https://pypi.org/pypi/{}/{}/json".format(project, version)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "dcc-mcp-unreal-release-guard"})
            with urllib.request.urlopen(request, timeout=30) as response:
                metadata = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and not require_existing:
                return {"publish": True, "retain": []}
            raise ReleaseGuardError("PyPI version metadata is unavailable: HTTP {}".format(exc.code)) from exc
        except urllib.error.URLError as exc:
            raise ReleaseGuardError("PyPI version metadata is unavailable") from exc
    urls = metadata.get("urls") if isinstance(metadata, dict) else None
    if not isinstance(urls, list):
        raise ReleaseGuardError("PyPI version metadata is malformed")
    if not urls:
        if require_existing:
            raise ReleaseGuardError("PyPI version has no published distributions")
        return {"publish": True, "retain": []}
    remote: Dict[str, str] = {}
    for item in urls:
        filename = item.get("filename") if isinstance(item, dict) else None
        digests = item.get("digests") if isinstance(item, dict) else None
        digest = digests.get("sha256") if isinstance(digests, dict) else None
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or filename in remote
        ):
            raise ReleaseGuardError("PyPI version metadata contains an invalid distribution identity")
        remote[filename] = digest
    if set(remote) != set(local):
        raise ReleaseGuardError("PyPI version distribution names differ from the staged release")
    for filename, path in local.items():
        if remote[filename] != _sha256(path):
            raise ReleaseGuardError("PyPI distribution {} has different bytes".format(filename))
    return {"publish": False, "retain": sorted(local)}


def _canonical_archive_names(names: Iterable[str]) -> List[str]:
    seen = set()
    canonical = []
    for name in names:
        if "\\" in name or name.startswith("/"):
            raise ReleaseGuardError("plugin archive contains a noncanonical member name")
        path = PurePosixPath(name)
        if any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != name.rstrip("/"):
            raise ReleaseGuardError("plugin archive contains a noncanonical member name")
        normalized = name.rstrip("/")
        if normalized in seen:
            raise ReleaseGuardError("plugin archive contains duplicate member names")
        seen.add(normalized)
        canonical.append(normalized)
    return canonical


def verify_plugin_archive(archive_path: Path, tag: str, source_sha: str, engine_tag: str) -> Dict[str, str]:
    tag = _canonical_tag(tag)
    source_sha = _canonical_sha(source_sha, "source_sha")
    version = tag[1:]
    if re.fullmatch(r"ue(?:4|5)\.[0-9]+", engine_tag) is None:
        raise ReleaseGuardError("engine tag is not canonical")
    expected_name = re.compile(
        r"DccMcpUnreal-{}-{}-(?:win64|source|python-only)\.zip".format(re.escape(version), re.escape(engine_tag))
    )
    if expected_name.fullmatch(archive_path.name) is None:
        raise ReleaseGuardError("plugin archive filename does not match its release identity")
    with zipfile.ZipFile(archive_path) as package:
        names = _canonical_archive_names(info.filename for info in package.infolist())
        if any(name.endswith(".dist-info/direct_url.json") for name in names):
            raise ReleaseGuardError("plugin archive must not contain direct_url.json")
        try:
            build_info = package.read("DccMcpUnreal/BUILD_INFO.txt").decode("utf-8")
            descriptor = json.loads(package.read("DccMcpUnreal/DccMcpUnreal.uplugin").decode("utf-8"))
        except KeyError as exc:
            raise ReleaseGuardError("plugin archive is missing embedded release identity") from exc
        for name in names:
            if name.endswith(".dist-info/RECORD") and "direct_url.json" in package.read(name).decode(
                "utf-8", errors="replace"
            ):
                raise ReleaseGuardError("plugin archive RECORD retains direct_url.json provenance")
    lines = build_info.splitlines()
    if not lines or lines[0] != "dcc-mcp-unreal {}".format(version):
        raise ReleaseGuardError("plugin archive version identity does not match the tag")
    try:
        provenance = dict(line.split("=", 1) for line in lines[1:])
    except ValueError as exc:
        raise ReleaseGuardError("plugin archive BUILD_INFO is malformed") from exc
    required = {
        "engine_tag",
        "python_version",
        "core_spec",
        "core_source",
        "source_commit",
        "package_mode",
        "python_plugin_name",
    }
    if set(provenance) != required:
        raise ReleaseGuardError("plugin archive BUILD_INFO contains nonportable provenance fields")
    if provenance["engine_tag"] != engine_tag:
        raise ReleaseGuardError("plugin archive engine identity does not match")
    if provenance["source_commit"] != source_sha:
        raise ReleaseGuardError("plugin archive source identity does not match")
    if descriptor.get("VersionName") != version:
        raise ReleaseGuardError("plugin descriptor version identity does not match the tag")
    lowered = build_info.casefold()
    if "file://" in lowered or "runner/work" in lowered or re.search(r"(?:^|[=\s])[a-z]:[\\/]", lowered):
        raise ReleaseGuardError("plugin archive BUILD_INFO contains a runner-local path")
    return {"archive": archive_path.name, "engine_tag": engine_tag, "source_sha": source_sha, "version": version}


def normalize_plugin_archive(
    archive_path: Path,
    tag: str,
    source_sha: str,
    engine_tag: str,
    python_version: str,
) -> Dict[str, str]:
    tag = _canonical_tag(tag)
    source_sha = _canonical_sha(source_sha, "source_sha")
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", python_version) is None:
        raise ReleaseGuardError("python version is not canonical")
    version = tag[1:]
    with zipfile.ZipFile(archive_path) as package:
        infos = package.infolist()
        names = _canonical_archive_names(info.filename for info in infos)
        if "DccMcpUnreal/BUILD_INFO.txt" not in names:
            raise ReleaseGuardError("plugin archive is missing BUILD_INFO.txt")
        descriptor = json.loads(package.read("DccMcpUnreal/DccMcpUnreal.uplugin").decode("utf-8"))
        if descriptor.get("VersionName") != version:
            raise ReleaseGuardError("plugin descriptor version identity does not match the tag")
        old_lines = package.read("DccMcpUnreal/BUILD_INFO.txt").decode("utf-8").splitlines()
        old_provenance = {}
        for line in old_lines[1:]:
            if "=" in line:
                key, value = line.split("=", 1)
                old_provenance[key] = value
        core_source = old_provenance.get("core_source")
        if core_source not in {"wheel", "local", "registry", "omitted"}:
            if old_provenance.get("skip_python_deps") == "True":
                core_source = "omitted"
            elif old_provenance.get("core_wheel"):
                core_source = "wheel"
            elif old_provenance.get("use_local_core") == "True":
                core_source = "local"
            else:
                core_source = "registry"
        build_info = "\n".join(
            (
                "dcc-mcp-unreal {}".format(version),
                "engine_tag={}".format(engine_tag),
                "python_version={}".format(python_version),
                "core_spec={}".format(old_provenance.get("core_spec", "dcc-mcp-core")),
                "core_source={}".format(core_source),
                "source_commit={}".format(source_sha),
                "package_mode={}".format(old_provenance.get("package_mode", "native")),
                "python_plugin_name={}".format(old_provenance.get("python_plugin_name", "PythonScriptPlugin")),
                "",
            )
        ).encode("utf-8")
        members = []
        for info in infos:
            if info.filename.endswith(".dist-info/direct_url.json"):
                continue
            data = package.read(info.filename)
            if info.filename == "DccMcpUnreal/BUILD_INFO.txt":
                data = build_info
            elif info.filename.endswith(".dist-info/RECORD"):
                rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
                rows = [row for row in rows if not row or not row[0].endswith("/direct_url.json")]
                rendered = io.StringIO(newline="")
                csv.writer(rendered, lineterminator="\n").writerows(rows)
                data = rendered.getvalue().encode("utf-8")
            members.append((info, data))
    temporary = archive_path.with_name(archive_path.name + ".normalized")
    if temporary.exists():
        raise ReleaseGuardError("refusing to replace an existing normalization temporary file")
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as normalized:
            for info, data in members:
                normalized.writestr(info, data)
        temporary.replace(archive_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"archive": archive_path.name, "engine_tag": engine_tag, "source_sha": source_sha, "version": version}


def _print_json(value: object) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _write_github_outputs(path: Path, resolved: Dict[str, object]) -> None:
    values = dict(resolved)
    values["should_release"] = resolved.get("mode") != "idle"
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for name in ("mode", "publish_pypi", "should_release", "source_sha", "tag_name", "version"):
            value = values[name]
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
            if "\n" in rendered or "\r" in rendered:
                raise ReleaseGuardError("GitHub output contains a newline")
            stream.write("{}={}\n".format(name, rendered))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    resolve = commands.add_parser("resolve-source")
    resolve.add_argument("--repo", type=Path, required=True)
    resolve.add_argument("--tag", default="")
    resolve.add_argument("--event-sha", required=True)
    resolve.add_argument("--github-output", type=Path)

    verify = commands.add_parser("verify-source")
    verify.add_argument("--repo", type=Path, required=True)
    verify.add_argument("--tag", required=True)
    verify.add_argument("--expected-sha", required=True)
    verify.add_argument("--require-tag", action="store_true")

    assets = commands.add_parser("plan-assets")
    assets.add_argument("--local-dir", type=Path, required=True)
    assets.add_argument("--existing-dir", type=Path, required=True)

    pypi = commands.add_parser("plan-pypi")
    pypi.add_argument("--dist-dir", type=Path, required=True)
    pypi.add_argument("--project", required=True)
    pypi.add_argument("--version", required=True)
    pypi.add_argument("--metadata-file", type=Path)
    pypi.add_argument("--require-existing", action="store_true")
    pypi.add_argument("--github-output", type=Path)

    archive = commands.add_parser("verify-plugin-archive")
    archive.add_argument("--archive", type=Path, required=True)
    archive.add_argument("--tag", required=True)
    archive.add_argument("--source-sha", required=True)
    archive.add_argument("--engine-tag", required=True)

    normalize = commands.add_parser("normalize-plugin-archive")
    normalize.add_argument("--archive", type=Path, required=True)
    normalize.add_argument("--tag", required=True)
    normalize.add_argument("--source-sha", required=True)
    normalize.add_argument("--engine-tag", required=True)
    normalize.add_argument("--python-version", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "resolve-source":
            resolved = resolve_source(args.repo.resolve(), args.tag, args.event_sha)
            if args.github_output is not None:
                _write_github_outputs(args.github_output, resolved)
            _print_json(resolved)
        elif args.command == "verify-source":
            _print_json(verify_source(args.repo.resolve(), args.tag, args.expected_sha, args.require_tag))
        elif args.command == "plan-assets":
            _print_json(plan_assets(args.local_dir.resolve(), args.existing_dir.resolve()))
        elif args.command == "plan-pypi":
            planned = plan_pypi(
                args.dist_dir.resolve(),
                args.project,
                args.version,
                args.metadata_file.resolve() if args.metadata_file is not None else None,
                args.require_existing,
            )
            if args.github_output is not None:
                with args.github_output.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write("publish_needed={}\n".format(str(bool(planned["publish"])).lower()))
            _print_json(planned)
        elif args.command == "verify-plugin-archive":
            _print_json(verify_plugin_archive(args.archive.resolve(), args.tag, args.source_sha, args.engine_tag))
        elif args.command == "normalize-plugin-archive":
            _print_json(
                normalize_plugin_archive(
                    args.archive.resolve(),
                    args.tag,
                    args.source_sha,
                    args.engine_tag,
                    args.python_version,
                )
            )
        else:  # pragma: no cover - argparse constrains commands
            raise ReleaseGuardError("unsupported command")
    except (OSError, ReleaseGuardError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print("release_guard: {}".format(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
