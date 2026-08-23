from __future__ import annotations

import json
import os
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

from dcc_mcp_unreal import install_cli

REPO_ROOT = Path(__file__).resolve().parents[1]


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
    completed = subprocess.CompletedProcess(
        args=[str(python_path)],
        returncode=0,
        stdout=json.dumps(
            {
                "python_version": "3.12.0",
                "adapter_version": install_cli.__version__,
                "core_version": "0.19.99",
            }
        ),
        stderr="",
    )
    monkeypatch.setattr(install_cli.subprocess, "run", lambda *_args, **_kwargs: completed)

    with pytest.raises(ValueError, match=r"0\.20\.0\+"):
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
    assert "0.20.0+" in result["verify"]["failure_reason"]


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
        "--timeout",
        "0",
    ]
    monkeypatch.setattr(
        dcc_mcp_core,
        "wait_for_sidecar_ready",
        lambda **kwargs: {
            "success": kwargs["probe_tool"] == "unreal_automation__mcp_self_check",
            "ready": True,
        },
    )
    install_args = install_cli._parser().parse_args(["install", *common, "--yes"])

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
    editor.parent.mkdir(parents=True)
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
