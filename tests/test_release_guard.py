from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE_GUARD = ROOT / "scripts" / "release_guard.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_release_identity(repo: Path, version: str) -> None:
    (repo / "src" / "dcc_mcp_unreal").mkdir(parents=True, exist_ok=True)
    (repo / "unreal" / "plugin").mkdir(parents=True, exist_ok=True)
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "dcc-mcp-unreal"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (repo / ".release-please-manifest.json").write_text(
        json.dumps({".": version}) + "\n",
        encoding="utf-8",
    )
    (repo / "src" / "dcc_mcp_unreal" / "__version__.py").write_text(
        f'__version__ = "{version}"  # x-release-please-version\n',
        encoding="utf-8",
    )
    (repo / "unreal" / "plugin" / "DccMcpUnreal.uplugin").write_text(
        json.dumps({"FileVersion": 3, "VersionName": version}) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def old_tag_from_new_main(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "repository"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "Release Test")
    _git(repo, "config", "user.email", "release@example.invalid")
    _write_release_identity(repo, "1.2.3")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore(main): release 1.2.3")
    old_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "v1.2.3")
    _write_release_identity(repo, "1.2.4")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore(main): release 1.2.4")
    new_sha = _git(repo, "rev-parse", "HEAD")
    return {"repo": repo, "old_sha": old_sha, "new_sha": new_sha}


def _guard(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RELEASE_GUARD), *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_manual_recovery_resolves_old_tag_commit_from_new_main(
    old_tag_from_new_main: dict[str, object],
) -> None:
    repo = Path(old_tag_from_new_main["repo"])
    completed = _guard(
        "resolve-source",
        "--repo",
        str(repo),
        "--tag",
        "v1.2.3",
        "--event-sha",
        str(old_tag_from_new_main["new_sha"]),
        cwd=repo,
    )

    assert completed.returncode == 0, completed.stderr
    resolved = json.loads(completed.stdout)
    assert resolved == {
        "mode": "recovery",
        "publish_pypi": False,
        "source_sha": old_tag_from_new_main["old_sha"],
        "tag_name": "v1.2.3",
        "version": "1.2.3",
    }
    assert resolved["source_sha"] != old_tag_from_new_main["new_sha"]


def test_source_verification_requires_exact_checkout_and_embedded_version(
    old_tag_from_new_main: dict[str, object],
) -> None:
    repo = Path(old_tag_from_new_main["repo"])
    checkout = repo.parent / "old-source"
    _git(repo, "worktree", "add", "--detach", str(checkout), str(old_tag_from_new_main["old_sha"]))

    accepted = _guard(
        "verify-source",
        "--repo",
        str(checkout),
        "--tag",
        "v1.2.3",
        "--expected-sha",
        str(old_tag_from_new_main["old_sha"]),
        cwd=checkout,
    )
    rejected = _guard(
        "verify-source",
        "--repo",
        str(repo),
        "--tag",
        "v1.2.3",
        "--expected-sha",
        str(old_tag_from_new_main["old_sha"]),
        cwd=repo,
    )

    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["source_sha"] == old_tag_from_new_main["old_sha"]
    assert rejected.returncode != 0
    assert "exact source commit" in rejected.stderr


def test_new_release_source_allows_missing_tag_but_recovery_requires_it(
    old_tag_from_new_main: dict[str, object],
) -> None:
    repo = Path(old_tag_from_new_main["repo"])
    automatic = _guard(
        "verify-source",
        "--repo",
        str(repo),
        "--tag",
        "v1.2.4",
        "--expected-sha",
        str(old_tag_from_new_main["new_sha"]),
        cwd=repo,
    )
    recovery = _guard(
        "verify-source",
        "--repo",
        str(repo),
        "--tag",
        "v1.2.4",
        "--expected-sha",
        str(old_tag_from_new_main["new_sha"]),
        "--require-tag",
        cwd=repo,
    )

    assert automatic.returncode == 0, automatic.stderr
    assert recovery.returncode != 0
    assert "required tag" in recovery.stderr


def test_release_subject_without_component_scope_is_recognized(
    old_tag_from_new_main: dict[str, object],
) -> None:
    repo = Path(old_tag_from_new_main["repo"])
    _write_release_identity(repo, "1.2.5")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: release 1.2.5")
    source_sha = _git(repo, "rev-parse", "HEAD")

    completed = _guard(
        "resolve-source",
        "--repo",
        str(repo),
        "--event-sha",
        source_sha,
        cwd=repo,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["tag_name"] == "v1.2.5"


def test_shell_output_can_be_written_to_the_current_step(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repository"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "Release Test")
    _git(repo, "config", "user.email", "release@example.invalid")
    _write_release_identity(repo, "1.2.6")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: release 1.2.6")
    source_sha = _git(repo, "rev-parse", "HEAD")

    completed = _guard(
        "resolve-source",
        "--shell-output",
        "--repo",
        str(repo),
        "--event-sha",
        source_sha,
        cwd=repo,
    )

    assert completed.returncode == 0, completed.stderr
    values = dict(line.split("=", 1) for line in completed.stdout.splitlines())
    assert values["should_release"] == "true"
    assert values["source_sha"] == source_sha
    assert values["tag_name"] == "v1.2.6"


def test_asset_plan_retains_only_digest_identical_assets(tmp_path: Path) -> None:
    local = tmp_path / "local"
    existing = tmp_path / "existing"
    local.mkdir()
    existing.mkdir()
    (local / "same.zip").write_bytes(b"same bytes")
    (existing / "same.zip").write_bytes(b"same bytes")
    (local / "new.whl").write_bytes(b"new bytes")

    planned = _guard(
        "plan-assets",
        "--local-dir",
        str(local),
        "--existing-dir",
        str(existing),
        cwd=tmp_path,
    )
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout) == {"retain": ["same.zip"], "upload": ["new.whl"]}

    (existing / "new.whl").write_bytes(b"different bytes")
    conflict = _guard(
        "plan-assets",
        "--local-dir",
        str(local),
        "--existing-dir",
        str(existing),
        cwd=tmp_path,
    )
    assert conflict.returncode != 0
    assert "different bytes" in conflict.stderr


def test_pypi_plan_is_recoverable_only_for_digest_identical_distributions(tmp_path: Path) -> None:
    distributions = tmp_path / "dist"
    distributions.mkdir()
    wheel = distributions / "dcc_mcp_unreal-1.2.3-py3-none-any.whl"
    source = distributions / "dcc_mcp_unreal-1.2.3.tar.gz"
    wheel.write_bytes(b"wheel bytes")
    source.write_bytes(b"source bytes")
    metadata = tmp_path / "pypi.json"
    metadata.write_text(
        json.dumps(
            {
                "urls": [
                    {"filename": wheel.name, "digests": {"sha256": _sha256(wheel)}},
                    {"filename": source.name, "digests": {"sha256": _sha256(source)}},
                ]
            }
        ),
        encoding="utf-8",
    )

    exact = _guard(
        "plan-pypi",
        "--dist-dir",
        str(distributions),
        "--project",
        "dcc-mcp-unreal",
        "--version",
        "1.2.3",
        "--metadata-file",
        str(metadata),
        cwd=tmp_path,
    )
    assert exact.returncode == 0, exact.stderr
    assert json.loads(exact.stdout) == {"publish": False, "retain": sorted([source.name, wheel.name])}

    remote = json.loads(metadata.read_text(encoding="utf-8"))
    remote["urls"][0]["digests"]["sha256"] = "0" * 64
    metadata.write_text(json.dumps(remote), encoding="utf-8")
    conflict = _guard(
        "plan-pypi",
        "--dist-dir",
        str(distributions),
        "--project",
        "dcc-mcp-unreal",
        "--version",
        "1.2.3",
        "--metadata-file",
        str(metadata),
        cwd=tmp_path,
    )
    assert conflict.returncode != 0
    assert "different bytes" in conflict.stderr


def _write_plugin_archive(path: Path, *, version: str, source_sha: str, engine_tag: str) -> None:
    build_info = "\n".join(
        (
            f"dcc-mcp-unreal {version}",
            f"engine_tag={engine_tag}",
            "python_version=3.12.0",
            "core_spec=dcc-mcp-core==0.20.13",
            "core_source=wheel",
            f"source_commit={source_sha}",
            "package_mode=native",
            "python_plugin_name=PythonScriptPlugin",
            "",
        )
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("DccMcpUnreal/BUILD_INFO.txt", build_info)
        archive.writestr(
            "DccMcpUnreal/DccMcpUnreal.uplugin",
            json.dumps({"FileVersion": 3, "VersionName": version}),
        )
        archive.writestr("DccMcpUnreal/python/dcc_mcp_unreal/__init__.py", f'__version__ = "{version}"\n')


def test_plugin_archive_verification_binds_tag_source_and_portable_metadata(
    old_tag_from_new_main: dict[str, object],
    tmp_path: Path,
) -> None:
    archive = tmp_path / "DccMcpUnreal-1.2.3-ue5.5-win64.zip"
    _write_plugin_archive(
        archive,
        version="1.2.3",
        source_sha=str(old_tag_from_new_main["old_sha"]),
        engine_tag="ue5.5",
    )

    accepted = _guard(
        "verify-plugin-archive",
        "--archive",
        str(archive),
        "--tag",
        "v1.2.3",
        "--source-sha",
        str(old_tag_from_new_main["old_sha"]),
        "--engine-tag",
        "ue5.5",
        cwd=tmp_path,
    )
    wrong_source = _guard(
        "verify-plugin-archive",
        "--archive",
        str(archive),
        "--tag",
        "v1.2.3",
        "--source-sha",
        str(old_tag_from_new_main["new_sha"]),
        "--engine-tag",
        "ue5.5",
        cwd=tmp_path,
    )

    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["source_sha"] == old_tag_from_new_main["old_sha"]
    assert wrong_source.returncode != 0
    assert "source identity" in wrong_source.stderr


def test_plugin_archive_rejects_builder_local_provenance(tmp_path: Path) -> None:
    archive = tmp_path / "DccMcpUnreal-1.2.3-ue5.8-win64.zip"
    _write_plugin_archive(archive, version="1.2.3", source_sha="a" * 40, engine_tag="ue5.8")
    with zipfile.ZipFile(archive, "a") as package:
        package.writestr(
            "DccMcpUnreal/python/dcc_mcp_unreal-1.2.3.dist-info/direct_url.json",
            json.dumps({"url": "file:///runner/work/project", "dir_info": {}}),
        )

    rejected = _guard(
        "verify-plugin-archive",
        "--archive",
        str(archive),
        "--tag",
        "v1.2.3",
        "--source-sha",
        "a" * 40,
        "--engine-tag",
        "ue5.8",
        cwd=tmp_path,
    )

    assert rejected.returncode != 0
    assert "direct_url.json" in rejected.stderr


def test_old_tag_archive_is_normalized_by_new_release_tooling(
    old_tag_from_new_main: dict[str, object],
    tmp_path: Path,
) -> None:
    archive = tmp_path / "DccMcpUnreal-1.2.3-ue5.7-win64.zip"
    local_root = tmp_path / "runner" / "source"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(
            "DccMcpUnreal/BUILD_INFO.txt",
            "\n".join(
                (
                    "dcc-mcp-unreal 1.2.3",
                    f"ue_root={tmp_path / 'UE_5.7'}",
                    f"python={tmp_path / 'python.exe'}",
                    "core_spec=dcc-mcp-core==0.20.13",
                    f"core_wheel={tmp_path / 'dcc_mcp_core.whl'}",
                    f"core_root={tmp_path / 'dcc-mcp-core'}",
                    "use_local_core=False",
                    "skip_python_deps=False",
                    "package_mode=native",
                    "python_plugin_name=PythonScriptPlugin",
                    "",
                )
            ),
        )
        package.writestr(
            "DccMcpUnreal/DccMcpUnreal.uplugin",
            json.dumps({"FileVersion": 3, "VersionName": "1.2.3"}),
        )
        package.writestr("DccMcpUnreal/python/dcc_mcp_unreal/__init__.py", '__version__ = "1.2.3"\n')
        package.writestr(
            "DccMcpUnreal/python/dcc_mcp_unreal-1.2.3.dist-info/direct_url.json",
            json.dumps({"url": local_root.as_uri(), "dir_info": {}}),
        )
        package.writestr(
            "DccMcpUnreal/python/dcc_mcp_unreal-1.2.3.dist-info/RECORD",
            "dcc_mcp_unreal/__init__.py,,\n"
            "dcc_mcp_unreal-1.2.3.dist-info/direct_url.json,,\n"
            "dcc_mcp_unreal-1.2.3.dist-info/RECORD,,\n",
        )

    normalized = _guard(
        "normalize-plugin-archive",
        "--archive",
        str(archive),
        "--tag",
        "v1.2.3",
        "--source-sha",
        str(old_tag_from_new_main["old_sha"]),
        "--engine-tag",
        "ue5.7",
        "--python-version",
        "3.12.10",
        cwd=tmp_path,
    )
    verified = _guard(
        "verify-plugin-archive",
        "--archive",
        str(archive),
        "--tag",
        "v1.2.3",
        "--source-sha",
        str(old_tag_from_new_main["old_sha"]),
        "--engine-tag",
        "ue5.7",
        cwd=tmp_path,
    )

    assert normalized.returncode == 0, normalized.stderr
    assert verified.returncode == 0, verified.stderr
    with zipfile.ZipFile(archive) as package:
        assert not any(name.endswith("direct_url.json") for name in package.namelist())
        build_info = package.read("DccMcpUnreal/BUILD_INFO.txt").decode("utf-8")
        record = package.read("DccMcpUnreal/python/dcc_mcp_unreal-1.2.3.dist-info/RECORD").decode("utf-8")
    assert str(tmp_path).casefold() not in build_info.casefold()
    assert "direct_url.json" not in record
