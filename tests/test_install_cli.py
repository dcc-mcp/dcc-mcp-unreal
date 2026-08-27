from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.9/3.10 CI
    import tomli as tomllib

import dcc_mcp_core
import pytest
from jsonschema import Draft202012Validator

from dcc_mcp_unreal import install_cli

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "tests" / "fixtures" / "adapter-install-sop-v1.schema.json"
CORE_2320_SCHEMA_SHA256 = "3ca25788439917b4d4c0617230a762f9797756b5b54f45c8c4149f975b90f904"


def _assert_sop_v1(result: dict) -> None:
    assert {
        "schema_version",
        "status",
        "dcc_type",
        "adapter_version",
        "core_version",
        "steps",
        "next_steps",
        "receipt_path",
        "verify",
    } <= result.keys()
    assert result["schema_version"] == 1
    assert result["status"] in {"planned", "running", "ok", "failed", "partial", "requires_restart"}
    assert set(result["verify"]) >= {"directly_usable", "failure_stage", "failure_reason"}
    for next_step in result["next_steps"]:
        assert set(next_step) >= {"id", "description", "why"}
        assert ("command" in next_step) ^ ("file_edit" in next_step)
    schema_bytes = SCHEMA_PATH.read_bytes()
    assert hashlib.sha256(schema_bytes).hexdigest() == CORE_2320_SCHEMA_SHA256
    schema = json.loads(schema_bytes)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result)


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    source = str(REPO_ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = source if not existing else source + os.pathsep + existing
    return env


def _run_cli(
    tmp_path: Path,
    *arguments: str,
    env_overrides: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    env = _cli_env()
    env.update(env_overrides or {})
    return subprocess.run(
        [sys.executable, "-m", "dcc_mcp_unreal.install_cli", *arguments],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _synthetic_host(tmp_path: Path) -> tuple[Path, Path]:
    engine = tmp_path / "UE_5.7"
    build_version = engine / "Engine" / "Build" / "Build.version"
    build_version.parent.mkdir(parents=True)
    build_version.write_text(
        json.dumps({"MajorVersion": 5, "MinorVersion": 7, "PatchVersion": 0}),
        encoding="utf-8",
    )
    project = tmp_path / "Sample" / "Sample.uproject"
    project.parent.mkdir()
    project.write_text(json.dumps({"FileVersion": 3, "EngineAssociation": "5.7"}), encoding="utf-8")
    if sys.platform == "win32":
        editor = engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    elif sys.platform == "darwin":
        editor = engine / "Engine" / "Binaries" / "Mac" / "UnrealEditor.app" / "Contents" / "MacOS" / "UnrealEditor"
    else:
        editor = engine / "Engine" / "Binaries" / "Linux" / "UnrealEditor"
    editor.parent.mkdir(parents=True)
    shutil.copyfile(sys.executable, editor)
    return engine, project


def test_install_dry_run_emits_sop_plan_without_writing(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "dcc_mcp_unreal.install_cli",
            "install",
            "--json",
            "--dry-run",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
        ],
        cwd=tmp_path,
        env=_cli_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    _assert_sop_v1(result)
    assert result["schema_version"] == 1
    assert result["status"] == "planned"
    assert result["dcc_type"] == "unreal"
    assert result["host"]["version"] == "5.7.0"
    assert result["install_state"] == "fresh"
    assert result["verify"]["directly_usable"] is False
    assert result["next_steps"] == [
        {
            "id": "execute-install",
            "description": "Execute the validated Unreal install plan.",
            "command": [
                "dcc-mcp-unreal",
                "install",
                "--json",
                "--yes",
                "--dcc-path",
                str(engine.resolve()),
                "--python",
                str(Path(sys.executable).resolve()),
                "--project",
                str(project.resolve()),
            ],
            "why": "The plan is valid but dry-run never mutates the project.",
        }
    ]
    assert not (project.parent / "Plugins" / "DccMcpUnreal").exists()
    assert not (project.parent / ".dcc-mcp" / "receipts" / "unreal.json").exists()


def test_receipt_driven_lifecycle_round_trip_preserves_project(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    original_project = project.read_text(encoding="utf-8")
    common = (
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    )

    installed = _run_cli(tmp_path, "install", *common, "--yes")

    assert installed.returncode == 40, installed.stderr
    install_result = json.loads(installed.stdout)
    assert install_result["verify"]["failure_stage"] == "readiness"
    plugin_root = project.parent / "Plugins" / "DccMcpUnreal"
    receipt = project.parent / ".dcc-mcp" / "receipts" / "unreal.json"
    assert (plugin_root / "DccMcpUnreal.uplugin").is_file()
    receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt_data["adapter_version"] == install_result["adapter_version"]
    assert receipt_data["plugin_root"] == str(plugin_root.resolve())
    project_data = json.loads(project.read_text(encoding="utf-8"))
    assert {"Name": "DccMcpUnreal", "Enabled": True} in project_data["Plugins"]

    previous_receipt = receipt.read_bytes()
    installed_again = _run_cli(tmp_path, "install", *common, "--yes")
    assert installed_again.returncode == 40, installed_again.stderr
    assert receipt.read_bytes() == previous_receipt

    status = _run_cli(tmp_path, "status", *common)
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["install_state"] == "current"

    removed = _run_cli(tmp_path, "uninstall", *common, "--yes")
    assert removed.returncode == 0, removed.stderr
    assert not plugin_root.exists()
    assert not receipt.exists()
    assert json.loads(project.read_text(encoding="utf-8")) == json.loads(original_project)

    removed_again = _run_cli(tmp_path, "uninstall", *common, "--yes")
    assert removed_again.returncode == 0, removed_again.stderr
    assert json.loads(removed_again.stdout)["install_state"] == "absent"


def test_install_discovers_host_without_dcc_path_override(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)

    planned = _run_cli(
        tmp_path,
        "install",
        "--json",
        "--dry-run",
        "--project",
        str(project),
        env_overrides={"UE_ROOT": str(engine), "DCC_MCP_INSTALL_PYTHON": sys.executable},
    )

    assert planned.returncode == 0, planned.stderr
    result = json.loads(planned.stdout)
    assert result["host"] == {
        "path": str(engine.resolve()),
        "version": "5.7.0",
        "source": "environment",
    }
    assert result["target_python"]["source"] == "environment"


def test_uninstall_fails_closed_when_project_enablement_changed(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = (
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    )
    assert _run_cli(tmp_path, "install", *common, "--yes").returncode == 40
    project_data = json.loads(project.read_text(encoding="utf-8"))
    project_data["Plugins"][0]["Enabled"] = False
    project.write_text(json.dumps(project_data), encoding="utf-8")

    removed = _run_cli(tmp_path, "uninstall", *common, "--yes")

    assert removed.returncode == 30, removed.stderr
    result = json.loads(removed.stdout)
    assert result["verify"]["failure_stage"] == "uninstall"
    assert (project.parent / "Plugins" / "DccMcpUnreal").is_dir()
    assert (project.parent / ".dcc-mcp" / "receipts" / "unreal.json").is_file()
    assert json.loads(project.read_text(encoding="utf-8"))["Plugins"][0]["Enabled"] is False


def test_wheel_configuration_ships_the_installable_plugin_payload() -> None:
    configuration = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    force_include = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include == {"unreal/plugin": "dcc_mcp_unreal/_plugin"}


def test_partial_status_has_one_machine_executable_recovery_step(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    (project.parent / "Plugins" / "DccMcpUnreal").mkdir(parents=True)

    status = _run_cli(
        tmp_path,
        "status",
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    )

    assert status.returncode == 10, status.stderr
    result = json.loads(status.stdout)
    assert result["status"] == "partial"
    assert len(result["next_steps"]) == 1
    assert result["next_steps"][0]["command"][0:2] == ["dcc-mcp-unreal", "status"]


def test_dry_run_wins_over_yes_for_uninstall(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = (
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
    )
    assert _run_cli(tmp_path, "install", *common, "--yes").returncode == 40
    plugin_root = project.parent / "Plugins" / "DccMcpUnreal"
    receipt = project.parent / ".dcc-mcp" / "receipts" / "unreal.json"

    planned = _run_cli(tmp_path, "uninstall", *common, "--yes", "--dry-run")

    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["status"] == "planned"
    assert plugin_root.is_dir()
    assert receipt.is_file()


def test_preflight_rejects_project_engine_mismatch(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    project.write_text(
        json.dumps({"FileVersion": 3, "EngineAssociation": "5.6"}),
        encoding="utf-8",
    )

    planned = _run_cli(
        tmp_path,
        "install",
        "--json",
        "--dry-run",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
    )

    assert planned.returncode == 10, planned.stderr
    result = json.loads(planned.stdout)
    assert result["verify"]["failure_stage"] == "preflight"
    assert "EngineAssociation 5.6" in result["verify"]["failure_reason"]


def test_uninstall_classifies_windows_style_plugin_lock(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    assert install_cli._execute(install_args)[0] == 40
    plugin_root = project.parent / "Plugins" / "DccMcpUnreal"
    real_replace = install_cli.os.replace

    def locked_replace(source, destination):
        if Path(source) == plugin_root:
            raise PermissionError("plugin binary is loaded")
        return real_replace(source, destination)

    monkeypatch.setattr(install_cli.os, "replace", locked_replace)
    uninstall_args = install_cli._parser().parse_args(["uninstall", *common, "--yes"])

    exit_code, result = install_cli._execute(uninstall_args)

    assert exit_code == 50
    assert result["status"] == "requires_restart"
    assert result["verify"]["failure_stage"] == "uninstall"
    assert plugin_root.is_dir()


def test_failed_upgrade_receipt_commit_restores_previous_install(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    assert install_cli._execute(install_args)[0] == 40
    plugin_root = project.parent / "Plugins" / "DccMcpUnreal"
    receipt_path = project.parent / ".dcc-mcp" / "receipts" / "unreal.json"
    previous_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    previous_receipt["adapter_version"] = "0.2.9"
    receipt_path.write_text(json.dumps(previous_receipt), encoding="utf-8")
    previous_files = install_cli._file_manifest(plugin_root)
    previous_project = project.read_bytes()
    previous_receipt_bytes = receipt_path.read_bytes()

    def fail_receipt(*_args, **_kwargs):
        raise OSError("injected receipt commit failure")

    monkeypatch.setattr(install_cli, "_write_receipt", fail_receipt)
    upgrade_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])

    exit_code, result = install_cli._execute(upgrade_args)

    assert exit_code == 30
    assert result["verify"]["failure_stage"] == "install"
    assert install_cli._file_manifest(plugin_root) == previous_files
    assert project.read_bytes() == previous_project
    assert receipt_path.read_bytes() == previous_receipt_bytes


def test_target_runtime_rejects_core_below_floor(monkeypatch, tmp_path: Path) -> None:
    python_path = tmp_path / "python"
    python_path.touch()
    completed = {
        "success": True,
        "returncode": 0,
        "stdout": json.dumps(
            {
                "python_version": "3.12.0",
                "adapter_version": install_cli.__version__,
                "core_version": "0.19.99",
            }
        ),
        "stderr": "",
        "truncated": False,
    }
    monkeypatch.setattr(install_cli, "_run_bounded_probe", lambda *_args, **_kwargs: completed)

    with pytest.raises(ValueError, match=r"0\.20\.13\+"):
        install_cli._target_runtime(python_path)


def test_lifecycle_cli_rejects_core_below_floor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(install_cli, "_core_version", lambda: "0.19.99")
    args = install_cli._parser().parse_args(
        ["status", "--json", "--dcc-path", str(tmp_path), "--python", sys.executable]
    )

    context, failure = install_cli._preflight(args)

    assert context is None
    assert failure is not None
    exit_code, result = failure
    assert exit_code == 10
    assert "0.20.13+" in result["verify"]["failure_reason"]


def test_verify_reports_directly_usable_only_after_typed_probe(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--instance-id",
        "11111111-1111-1111-1111-111111111111",
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    context = install_cli._resolve_context(install_args)
    monkeypatch.setattr(
        dcc_mcp_core,
        "wait_for_sidecar_ready",
        lambda **kwargs: _bound_readiness(context),
    )

    exit_code, result = install_cli._execute(install_args)

    assert exit_code == 0
    _assert_sop_v1(result)
    assert result["verify"] == {
        "directly_usable": True,
        "failure_stage": None,
        "failure_reason": None,
    }


def test_readiness_failure_returns_exact_editor_launch_step(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    if sys.platform == "win32":
        editor = engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    elif sys.platform == "darwin":
        editor = engine / "Engine" / "Binaries" / "Mac" / "UnrealEditor.app" / "Contents" / "MacOS" / "UnrealEditor"
    else:
        editor = engine / "Engine" / "Binaries" / "Linux" / "UnrealEditor"
    editor.parent.mkdir(parents=True, exist_ok=True)
    editor.touch()
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])

    exit_code, result = install_cli._execute(install_args)

    assert exit_code == 40
    assert result["verify"]["failure_stage"] == "readiness"
    assert result["next_steps"] == [
        {
            "id": "launch-unreal-editor",
            "description": "Launch the selected Unreal Editor project so its DCC MCP plugin can become ready.",
            "command": [str(editor.resolve()), str(project.resolve())],
            "why": "The installed plugin passed static checks, but no typed Unreal readiness probe succeeded.",
        }
    ]


def test_install_rejects_payload_version_mismatch_before_commit(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "DccMcpUnreal.uplugin").write_text(
        json.dumps({"FileVersion": 3, "VersionName": "0.2.0"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(install_cli, "_plugin_source", lambda: (payload, "test"))
    args = install_cli._parser().parse_args(
        [
            "install",
            "--json",
            "--yes",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
        ]
    )

    exit_code, result = install_cli._execute(args)

    assert exit_code == 20
    assert result["verify"]["failure_stage"] == "acquire"
    assert not (project.parent / "Plugins" / "DccMcpUnreal").exists()
    assert not (project.parent / ".dcc-mcp" / "receipts" / "unreal.json").exists()


def test_root_install_runbook_has_required_sop_sections_and_catalog_handoff() -> None:
    runbook = (REPO_ROOT / "install.md").read_text(encoding="utf-8")

    for section in (
        "## Requirements",
        "## Supported versions",
        "## Agent quick path",
        "## Manual path",
        "## Verify",
        "## Upgrade",
        "## Uninstall",
        "## Troubleshooting",
    ):
        assert section in runbook
    assert "Windows" in runbook and "macOS" in runbook and "Linux" in runbook
    assert "https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-unreal/main/install.md" in runbook


def test_repair_refuses_unreceipted_files_inside_plugin_root(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = (
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    )
    assert _run_cli(tmp_path, "install", *common, "--yes").returncode == 40
    user_file = project.parent / "Plugins" / "DccMcpUnreal" / "StudioOwned.txt"
    user_file.write_text("preserve me", encoding="utf-8")

    repaired = _run_cli(tmp_path, "install", *common, "--yes")

    assert repaired.returncode == 10, repaired.stderr
    result = json.loads(repaired.stdout)
    assert result["install_state"] == "partial"
    assert "unreceipted" in result["verify"]["failure_reason"]
    assert user_file.read_text(encoding="utf-8") == "preserve me"


@pytest.mark.parametrize(
    "value",
    (
        "0.20.13rc1",
        "garbage0.20.13",
        "0.20.13suffix",
        " 0.20.13",
        "0.20",
        "0.20.13.1",
        "0." + "9" * 5000 + ".1",
    ),
)
def test_versions_are_bounded_canonical_finals(value: str) -> None:
    with pytest.raises(ValueError, match="canonical"):
        install_cli._version_tuple(value)


def test_zero_byte_editor_is_not_a_usable_host(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    editor = install_cli._editor_executable(engine)
    assert editor is not None
    editor.write_bytes(b"")
    args = install_cli._parser().parse_args(
        [
            "status",
            "--json",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
        ]
    )

    context, failure = install_cli._preflight(args)

    assert context is None
    assert failure is not None
    assert failure[0] == 10
    assert "editor" in failure[1]["verify"]["failure_reason"].lower()


def test_manifest_owns_directories_and_rejects_unexpected_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    (root / "Content" / "Python").mkdir(parents=True)
    (root / "Content" / "Python" / "init_unreal.py").write_text("pass\n", encoding="utf-8")
    manifest = install_cli._file_manifest(root)
    assert {item["type"] for item in manifest} == {"directory", "file"}
    receipt = {"ownership": manifest}
    assert install_cli._manifest_matches(root, receipt)[:2] == (True, "")

    (root / "StudioOwnedEmpty").mkdir()
    matches, reason, has_unreceipted = install_cli._manifest_matches(root, receipt)

    assert matches is False
    assert has_unreceipted is True
    assert "unreceipted" in reason


def test_target_runtime_rejects_shadow_module_outside_distribution(monkeypatch, tmp_path: Path) -> None:
    python_path = tmp_path / "python"
    python_path.touch()
    site = tmp_path / "site-packages"
    shadow_origin = tmp_path / "shadow" / "dcc_mcp_unreal" / "__init__.py"
    core_origin = site / "dcc_mcp_core" / "__init__.py"
    shadow_origin.parent.mkdir(parents=True)
    core_origin.parent.mkdir(parents=True)
    shadow_origin.write_text("# shadow\n", encoding="utf-8")
    core_origin.write_text("# core\n", encoding="utf-8")
    completed = {
        "success": True,
        "returncode": 0,
        "stdout": json.dumps(
            {
                "python_executable": str(python_path.resolve()),
                "python_version": "3.12.0",
                "adapter": {
                    "name": "dcc-mcp-unreal",
                    "version": install_cli.__version__,
                    "module_version": install_cli.__version__,
                    "origin": str(shadow_origin.resolve()),
                    "distribution_root": str(site.resolve()),
                    "record": "dcc_mcp_unreal/__init__.py",
                    "record_hash": None,
                    "record_size": None,
                    "direct_url": None,
                },
                "core": {
                    "name": "dcc-mcp-core",
                    "version": install_cli.MIN_CORE_VERSION,
                    "module_version": None,
                    "origin": str(core_origin.resolve()),
                    "distribution_root": str(site.resolve()),
                    "record": "dcc_mcp_core/__init__.py",
                    "record_hash": None,
                    "record_size": None,
                    "direct_url": None,
                },
            }
        ),
        "stderr": "",
        "truncated": False,
    }
    monkeypatch.setattr(install_cli, "_run_bounded_probe", lambda *_args, **_kwargs: completed)

    with pytest.raises(ValueError, match="origin"):
        install_cli._target_runtime(python_path)


def _distribution_identity(
    origin: Path,
    root: Path,
    *,
    record: Optional[str] = None,
    direct_url: Optional[dict] = None,
    name: str = "dcc-mcp-unreal",
    version: str = install_cli.__version__,
) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    return {
        "name": name,
        "version": version,
        "module_version": install_cli.__version__,
        "origin": str(origin.absolute()),
        "distribution_root": str(root.absolute()),
        "record": record,
        "record_hash": None,
        "record_size": None,
        "direct_url": direct_url,
    }


@pytest.mark.parametrize("editable", (True, False, None))
def test_distribution_identity_accepts_owned_local_source_checkout(tmp_path: Path, editable: Optional[bool]) -> None:
    source_root = tmp_path / "source"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    dir_info = {} if editable is None else {"editable": editable}
    identity = _distribution_identity(
        origin,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": dir_info},
    )

    assert install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal") == str(origin.absolute())


def test_distribution_identity_accepts_installed_wheel_record(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    origin = site / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    identity = _distribution_identity(origin, site, record="dcc_mcp_unreal/__init__.py")

    assert install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal") == str(origin.absolute())


@pytest.mark.parametrize(
    ("field", "value"),
    (("record_size", 1), ("record_hash", "sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")),
)
def test_distribution_identity_rejects_record_metadata_mismatch(tmp_path: Path, field: str, value: object) -> None:
    site = tmp_path / "site-packages"
    origin = site / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    identity = _distribution_identity(origin, site, record="dcc_mcp_unreal/__init__.py")
    identity[field] = value

    with pytest.raises(ValueError, match="metadata"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


def test_target_runtime_accepts_the_active_distribution_context() -> None:
    runtime = install_cli._target_runtime(Path(sys.executable))

    assert runtime["adapter_version"] == install_cli.__version__
    assert Path(runtime["adapter_origin"]).name == "__init__.py"
    assert Path(runtime["core_origin"]).name == "__init__.py"


def test_distribution_identity_rejects_same_bytes_from_independent_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    owned = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    replacement = tmp_path / "replacement" / "src" / "dcc_mcp_unreal" / "__init__.py"
    owned.parent.mkdir(parents=True)
    replacement.parent.mkdir(parents=True)
    owned.write_text("# identical\n", encoding="utf-8")
    replacement.write_bytes(owned.read_bytes())
    identity = _distribution_identity(
        replacement,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": {}},
    )

    with pytest.raises(ValueError, match="owned"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


def test_distribution_identity_rejects_symlinked_source_package(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    payload = tmp_path / "payload" / "dcc_mcp_unreal"
    payload.mkdir(parents=True)
    (payload / "__init__.py").write_text("# package\n", encoding="utf-8")
    package_link = source_root / "src" / "dcc_mcp_unreal"
    package_link.parent.mkdir(parents=True)
    if sys.platform == "win32":
        linked = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(package_link), str(payload)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert linked.returncode == 0, linked.stderr or linked.stdout
    else:
        os.symlink(payload, package_link, target_is_directory=True)
    origin = package_link / "__init__.py"
    identity = _distribution_identity(
        origin,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": {}},
    )

    with pytest.raises(ValueError, match="link|reparse"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


def test_distribution_identity_rejects_hardlinked_module(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    independent = tmp_path / "independent.py"
    origin.parent.mkdir(parents=True)
    independent.write_text("# package\n", encoding="utf-8")
    os.link(independent, origin)
    identity = _distribution_identity(
        origin,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": {}},
    )

    with pytest.raises(ValueError, match="link"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


@pytest.mark.parametrize(
    ("field", "value"),
    (("name", "foreign-distribution"), ("version", "0.0.1")),
)
def test_distribution_identity_rejects_mismatched_product_metadata(tmp_path: Path, field: str, value: str) -> None:
    source_root = tmp_path / "source"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    identity = _distribution_identity(
        origin,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": {}},
    )
    identity[field] = value

    with pytest.raises(ValueError, match="identity|version"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


@pytest.mark.parametrize("editable", (0, 1, "true", {}, []))
def test_distribution_identity_rejects_malformed_source_metadata(tmp_path: Path, editable: object) -> None:
    source_root = tmp_path / "source"
    origin = source_root / "src" / "dcc_mcp_unreal" / "__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# package\n", encoding="utf-8")
    identity = _distribution_identity(
        origin,
        tmp_path / "site-packages",
        direct_url={"url": source_root.as_uri(), "dir_info": {"editable": editable}},
    )

    with pytest.raises(ValueError, match="owned"):
        install_cli._owned_module_origin(identity, "dcc-mcp-unreal", "dcc_mcp_unreal")


def _bound_readiness(context: dict, *, instance_id: str = "11111111-1111-1111-1111-111111111111") -> dict:
    identity = {
        "instance_id": instance_id,
        "host_pid": 4242,
        "process_start_token": "unreal-start-token",
        "editor_executable": str(context["editor_path"]),
        "project_file": str(context["project_file"]),
        "plugin_root": str(context["plugin_root"]),
        "engine_version": context["engine_version"],
        "adapter_version": install_cli.__version__,
        "core_version": context["runtime"]["core_version"],
        "adapter_origin": context["runtime"]["adapter_origin"],
        "core_origin": context["runtime"]["core_origin"],
    }
    return {
        "success": True,
        "ready": True,
        "entry": {"instance_id": instance_id, "parent_pid": 4242},
        "probe": {"success": True, "result": {"success": True, "context": {"install_identity": identity}}},
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("instance_id", "22222222-2222-2222-2222-222222222222"),
        ("host_pid", 5151),
        ("process_start_token", "bad"),
        ("editor_executable", "foreign-editor"),
        ("project_file", "foreign-project"),
        ("plugin_root", "foreign-plugin"),
        ("engine_version", "5.6.0"),
        ("adapter_version", "0.0.1"),
        ("core_version", "0.0.1"),
        ("adapter_origin", "foreign-adapter"),
        ("core_origin", "foreign-core"),
    ),
)
def test_readiness_identity_rejects_each_foreign_runtime_axis(tmp_path: Path, field: str, replacement: object) -> None:
    engine, project = _synthetic_host(tmp_path)
    args = install_cli._parser().parse_args(
        [
            "verify",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
            "--instance-id",
            "11111111-1111-1111-1111-111111111111",
        ]
    )
    context = install_cli._resolve_context(args)
    readiness = _bound_readiness(context)
    readiness["probe"]["result"]["context"]["install_identity"][field] = replacement

    identity, reason = install_cli._readiness_identity(
        args,
        context,
        {"instance_selector": context["instance_id"], "runtime_identity": None},
        readiness,
    )

    assert identity is None
    assert reason is not None
    assert field in reason


def test_receipted_process_token_rejects_pid_reuse(tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    args = install_cli._parser().parse_args(
        [
            "verify",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
            "--instance-id",
            "11111111-1111-1111-1111-111111111111",
        ]
    )
    context = install_cli._resolve_context(args)
    readiness = _bound_readiness(context)
    previous = dict(readiness["probe"]["result"]["context"]["install_identity"])
    readiness["probe"]["result"]["context"]["install_identity"]["process_start_token"] = "replacement-start-token"

    identity, reason = install_cli._readiness_identity(
        args,
        context,
        {"instance_selector": context["instance_id"], "runtime_identity": previous},
        readiness,
    )

    assert identity is None
    assert reason == "typed readiness identity changed from the receipted editor process"


def test_verify_rejects_foreign_project_instance(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--instance-id",
        "11111111-1111-1111-1111-111111111111",
        "--timeout",
        "0",
    ]
    args = install_cli._parser().parse_args(["install", *common, "--yes"])
    context = install_cli._resolve_context(args)
    readiness = _bound_readiness(context)
    readiness["probe"]["result"]["context"]["install_identity"]["project_file"] = str(
        (tmp_path / "Foreign.uproject").resolve()
    )
    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", lambda **_kwargs: readiness)

    exit_code, result = install_cli._execute(args)

    assert exit_code == 40
    assert result["verify"]["directly_usable"] is False
    assert "project_file" in result["verify"]["failure_reason"]
    assert not (project.parent / "Plugins" / "DccMcpUnreal").exists()
    assert not (project.parent / ".dcc-mcp" / "receipts" / "unreal.json").exists()


@pytest.mark.parametrize(
    ("verb", "extra", "expected_exit"),
    (
        ("install", ["--dry-run"], 0),
        ("status", [], 0),
        ("verify", [], 40),
        ("uninstall", ["--yes"], 0),
        ("upgrade", ["--dry-run"], 0),
    ),
)
def test_all_public_verbs_validate_against_core_draft_schema(
    tmp_path: Path, verb: str, extra: list[str], expected_exit: int
) -> None:
    engine, project = _synthetic_host(tmp_path)
    args = install_cli._parser().parse_args(
        [
            verb,
            "--json",
            "--dcc-path",
            str(engine),
            "--python",
            sys.executable,
            "--project",
            str(project),
            "--timeout",
            "0",
            *extra,
        ]
    )

    exit_code, result = install_cli._execute(args)

    assert exit_code == expected_exit
    _assert_sop_v1(result)


def test_upgrade_keeps_prior_install_until_bound_verify_succeeds(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--instance-id",
        "11111111-1111-1111-1111-111111111111",
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    context = install_cli._resolve_context(install_args)
    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", lambda **_kwargs: _bound_readiness(context))
    assert install_cli._execute(install_args)[0] == 0
    plugin_root = context["plugin_root"]
    receipt_path = context["receipt_path"]
    prior_files = install_cli._file_manifest(plugin_root)
    prior_project = project.read_bytes()
    prior_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    prior_receipt["adapter_version"] = "0.2.9"
    receipt_path.write_text(json.dumps(prior_receipt), encoding="utf-8")
    prior_receipt_bytes = receipt_path.read_bytes()
    foreign = _bound_readiness(context)
    foreign["probe"]["result"]["context"]["install_identity"]["plugin_root"] = str(
        (tmp_path / "ForeignPlugin").resolve()
    )
    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", lambda **_kwargs: foreign)
    upgrade_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])

    exit_code, result = install_cli._execute(upgrade_args)

    assert exit_code == 40
    assert "plugin_root" in result["verify"]["failure_reason"]
    assert install_cli._file_manifest(plugin_root) == prior_files
    assert project.read_bytes() == prior_project
    assert receipt_path.read_bytes() == prior_receipt_bytes
    assert not list(plugin_root.parent.glob(".DccMcpUnreal.*-*"))


def test_upgrade_without_live_selector_keeps_rollback_until_later_bound_verify(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    assert install_cli._execute(install_args)[0] == 40
    context = install_cli._resolve_context(install_args)
    plugin_root = context["plugin_root"]
    receipt_path = context["receipt_path"]
    prior_files = install_cli._file_manifest(plugin_root)
    prior_project = project.read_bytes()
    prior_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    prior_receipt["adapter_version"] = "0.2.9"
    receipt_path.write_text(json.dumps(prior_receipt), encoding="utf-8")
    prior_receipt_bytes = receipt_path.read_bytes()

    upgrade_args = install_cli._parser().parse_args(["upgrade", *common, "--yes"])
    exit_code, _ = install_cli._execute(upgrade_args)
    pending_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert exit_code == 40
    assert pending_receipt["transaction"]["state"] == "awaiting-bound-verify"
    assert Path(pending_receipt["transaction"]["backup_plugin"]).is_dir()
    status_args = install_cli._parser().parse_args(["status", *common])
    status_code, status_result = install_cli._execute(status_args)
    uninstall_args = install_cli._parser().parse_args(["uninstall", *common, "--yes"])
    uninstall_code, uninstall_result = install_cli._execute(uninstall_args)

    assert status_code == 0
    assert status_result["verify"]["failure_stage"] == "readiness"
    assert status_result["next_steps"][0]["id"] == "launch-unreal-editor"
    assert uninstall_code == 10
    assert "awaiting exact-instance" in uninstall_result["verify"]["failure_reason"]
    assert Path(pending_receipt["transaction"]["backup_plugin"]).is_dir()

    verify_args = install_cli._parser().parse_args(
        [
            "verify",
            *common,
            "--instance-id",
            "11111111-1111-1111-1111-111111111111",
        ]
    )
    verify_context = install_cli._resolve_context(verify_args)
    foreign = _bound_readiness(verify_context)
    foreign["probe"]["result"]["context"]["install_identity"]["project_file"] = str(
        (tmp_path / "Foreign.uproject").resolve()
    )
    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", lambda **_kwargs: foreign)

    exit_code, result = install_cli._execute(verify_args)

    assert exit_code == 40
    assert "project_file" in result["verify"]["failure_reason"]
    assert install_cli._file_manifest(plugin_root) == prior_files
    assert project.read_bytes() == prior_project
    assert receipt_path.read_bytes() == prior_receipt_bytes
    assert not list(plugin_root.parent.glob(".DccMcpUnreal.*-*"))


def test_uninstall_delete_failure_restores_every_owned_byte(monkeypatch, tmp_path: Path) -> None:
    engine, project = _synthetic_host(tmp_path)
    common = [
        "--json",
        "--dcc-path",
        str(engine),
        "--python",
        sys.executable,
        "--project",
        str(project),
        "--instance-id",
        "11111111-1111-1111-1111-111111111111",
        "--timeout",
        "0",
    ]
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])
    context = install_cli._resolve_context(install_args)
    monkeypatch.setattr(dcc_mcp_core, "wait_for_sidecar_ready", lambda **_kwargs: _bound_readiness(context))
    assert install_cli._execute(install_args)[0] == 0
    plugin_root = context["plugin_root"]
    receipt_path = context["receipt_path"]
    prior_files = install_cli._file_manifest(plugin_root)
    prior_project = project.read_bytes()
    prior_receipt = receipt_path.read_bytes()
    real_remove = install_cli._remove_tree

    def fail_quarantine(path: Path) -> None:
        if ".uninstall-" in path.name:
            victim = next(item for item in path.rglob("*") if item.is_file())
            victim.unlink()
            raise OSError("injected partial quarantine delete")
        real_remove(path)

    monkeypatch.setattr(install_cli, "_remove_tree", fail_quarantine)
    uninstall_args = install_cli._parser().parse_args(["uninstall", *common, "--yes"])

    exit_code, result = install_cli._execute(uninstall_args)

    assert exit_code == 30
    assert result["verify"]["failure_stage"] == "uninstall"
    assert install_cli._file_manifest(plugin_root) == prior_files
    assert project.read_bytes() == prior_project
    assert receipt_path.read_bytes() == prior_receipt
