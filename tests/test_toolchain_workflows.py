import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BUILD_WORKFLOW = ROOT / ".github" / "workflows" / "build-uplugin.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
RELEASE_CONFIG = ROOT / "release-please-config.json"
VERSION_MODULE = ROOT / "src" / "dcc_mcp_unreal" / "__version__.py"
CONFIGURE_SCRIPT = ROOT / ".github" / "scripts" / "configure-ubt-toolchain.ps1"
PLUGIN_MODULE = ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpUnrealModule.cpp"
PLUGIN_RULES = ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "DccMcpUnreal.Build.cs"
STANDALONE_INSTALLER = ROOT / "scripts" / "install-standalone.ps1"
SMOKE_SCRIPT = ROOT / "scripts" / "run_ue_smoke.ps1"
STANDALONE_BUILDER = ROOT / "tools" / "build_binary.py"
STANDALONE_README = ROOT / "packaging" / "standalone-README.md"
PYOXIDIZER_CONFIG = ROOT / "pyoxidizer.bzl"
BUILD_DISTRIBUTABLE = ROOT / "packaging" / "build_distributable.py"
BUILD_PLUGIN = ROOT / "packaging" / "build_plugin.py"
BUILD_PACKAGE_SCRIPT = (
    ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-build-package" / "scripts" / "_build_package.py"
)
VX_CONFIG = ROOT / "vx.toml"


def _configure_toolchain(ue_version: str, tmp_path: Path) -> str:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is required to exercise the workflow helper")

    environment_file = tmp_path / "github-env.txt"
    subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(CONFIGURE_SCRIPT),
            "-UEVersion",
            ue_version,
            "-EnvironmentFile",
            str(environment_file),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return environment_file.read_text(encoding="utf-8-sig")


def test_plugin_workflows_use_job_scoped_ubt_toolchain_configuration() -> None:
    text = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert ".github/scripts/configure-ubt-toolchain.ps1" in text
    assert "$env:APPDATA" not in text
    assert "DCC_MCP_UNREAL_UBT_APPDATA" not in text

    release = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    assert release["jobs"]["build-unreal-plugin"]["uses"] == ("./.github/workflows/build-uplugin.yml")


@pytest.mark.parametrize("ue_version", ["5.7", "5.8"])
def test_toolchain_script_selects_latest_valid_compiler_for_modern_ue(
    tmp_path: Path,
    ue_version: str,
) -> None:
    environment = _configure_toolchain(ue_version, tmp_path)

    assert environment == (
        "UnrealBuildTool_WindowsPlatform__CompilerVersion=Latest\n"
        "UnrealBuildTool_BuildConfiguration__bAllowUBAExecutor=false\n"
        "UnrealBuildTool_BuildConfiguration__MaxParallelActions=1\n"
    )


def test_build_workflow_no_longer_writes_global_ubt_config() -> None:
    text = BUILD_WORKFLOW.read_text(encoding="utf-8")

    assert '".github/scripts/configure-ubt-toolchain.ps1"' in text
    assert '"$env:APPDATA\\Unreal Engine\\UnrealBuildTool"' not in text
    assert "Force MSVC 14.36 toolchain via BuildConfiguration.xml" not in text


def test_build_workflow_targets_available_unreal_versions() -> None:
    workflow = yaml.safe_load(BUILD_WORKFLOW.read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["build-uplugin"]["strategy"]["matrix"]["include"]

    assert [entry["ue_version"] for entry in matrix] == ["5.5", "5.7", "5.8", "4.18"]
    assert all(entry["ue_root"] == rf"F:\UE\UE_{entry['ue_version']}" for entry in matrix)
    assert matrix[3]["package_mode"] == "native"
    assert matrix[3]["artifact_suffix"] == "win64"
    assert (
        "github.event.pull_request.head.repo.full_name == github.repository" in workflow["jobs"]["build-uplugin"]["if"]
    )
    assert all("vctoolchain_version" not in entry for entry in matrix)


def test_ue418_native_bridge_uses_the_core_sidecar_wire_contract() -> None:
    module = PLUGIN_MODULE.read_text(encoding="utf-8")
    rules = PLUGIN_RULES.read_text(encoding="utf-8")

    assert "qtserver://127.0.0.1:" in module
    assert "dcc-mcp-server.exe" in module
    assert "DCC_MCP_UNREAL_RUNTIME" in module
    assert "bAutoPythonSupported = false" in module
    assert "PythonScriptPlugin is active; skipping the standalone sidecar" in module
    for action in ("list_actors", "spawn_actor", "delete_actor", "get_actor_transform", "set_actor_transform"):
        assert f"unreal_actors__{action}" in module
    for action in ("get_level_info", "save_level"):
        assert f"unreal_level__{action}" in module
    for action in ("list_assets", "create_blueprint"):
        assert f"unreal_assets__{action}" in module
    for action in ("create_blueprint_class", "add_component_to_blueprint", "compile_blueprint"):
        assert f"unreal_blueprints__{action}" in module
    assert all(
        dependency in rules for dependency in ('"AssetRegistry"', '"Json"', '"Networking"', '"Sockets"', '"UnrealEd"')
    )


def test_smoke_script_supports_ue4_and_ue5_editor_commandlets() -> None:
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "UE4Editor-Cmd.exe" in script
    assert "UnrealEditor-Cmd.exe" in script


def test_smoke_script_does_not_promote_editor_stderr_to_a_terminating_error() -> None:
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert '$ErrorActionPreference = "Continue"' in script
    assert "$previousErrorActionPreference" in script


def test_smoke_script_validates_the_native_automation_report() -> None:
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert '$nativeReport = Join-Path $report "index.json"' in script
    assert "$nativeData.failed" in script
    assert "$nativeData.succeededWithWarnings" in script


def test_vx_exposes_a_native_ue426_package_target() -> None:
    config = VX_CONFIG.read_text(encoding="utf-8")

    assert 'UE_4_26_ROOT = "C:\\\\Program Files\\\\Epic Games\\\\UE_4.26"' in config
    assert "build-ue4.26" in config
    assert "--mode native" in config


def test_native_sidecar_participates_in_gateway_discovery() -> None:
    source = PLUGIN_MODULE.read_text(encoding="utf-8")

    assert "--no-ensure-gateway" not in source


def test_build_workflow_vendors_the_base_core_wheel() -> None:
    text = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert '$requirement = "dcc-mcp-core"' in text
    assert "dcc-mcp-core==$($tag -replace" in text
    assert "dcc_mcp_core-*.whl" in text
    assert "dcc_mcp_core_semantic-" not in text


def test_core_floor_includes_explicit_ui_control_resume_fix() -> None:
    requirement = "dcc-mcp-core>=0.19.77,<1.0.0"

    assert requirement in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert requirement in BUILD_PACKAGE_SCRIPT.read_text(encoding="utf-8")
    assert requirement in BUILD_PLUGIN.read_text(encoding="utf-8")
    assert requirement in BUILD_DISTRIBUTABLE.read_text(encoding="utf-8")


def test_ue4_uat_uses_precompiled_automation_tool_on_restricted_runners() -> None:
    builder = BUILD_DISTRIBUTABLE.read_text(encoding="utf-8")

    assert 'engine_tag.startswith("ue4.")' in builder
    assert '"ue5.5"' in builder
    assert '"AutomationTool.exe"' in builder
    assert 'cmd.append("-nocompile")' in builder
    assert 'os.environ["uebp_LogFolder"] = str(uat_log_dir)' in builder
    assert "with temporarily_clear_legacy_ubt_user_config(uat_dir.parent):" in builder


def test_release_jobs_run_after_release_please_is_skipped_for_tag_events() -> None:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    for job_name in ("build", "build-unreal-plugin", "standalone", "publish", "attach-release-assets"):
        assert "always()" in jobs[job_name]["if"]

    assert "needs.build.result == 'success'" in jobs["publish"]["if"]
    assert "needs.publish.result == 'success'" in jobs["attach-release-assets"]["if"]
    assert "needs.build-unreal-plugin.result == 'success'" in jobs["attach-release-assets"]["if"]


def test_release_please_runs_on_main_without_publishing_ordinary_pushes() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    jobs = workflow["jobs"]
    tag_push = "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"

    assert "branches: [main]" in text
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in jobs["release-please"]["if"]
    for job_name in ("build", "build-unreal-plugin", "standalone", "attach-release-assets"):
        assert tag_push in jobs[job_name]["if"]
        assert "github.event_name == 'push' ||" not in jobs[job_name]["if"]
    assert tag_push not in jobs["publish"]["if"]
    assert "needs.release-please.outputs.release_created == 'true'" in jobs["publish"]["if"]


def test_release_please_can_update_the_runtime_version_module() -> None:
    config = json.loads(RELEASE_CONFIG.read_text(encoding="utf-8"))

    assert {"type": "generic", "path": "src/dcc_mcp_unreal/__version__.py"} in (config["packages"]["."]["extra-files"])
    assert "x-release-please-version" in VERSION_MODULE.read_text(encoding="utf-8")


def test_release_plugin_build_uses_registry_free_embedded_python() -> None:
    release = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    plugin_job = release["jobs"]["build-unreal-plugin"]

    assert plugin_job["uses"] == "./.github/workflows/build-uplugin.yml"
    assert plugin_job["with"]["core_version"] == ("${{ github.event.inputs.core_version || 'latest' }}")
    assert plugin_job["secrets"] == "inherit"

    build = yaml.safe_load(BUILD_WORKFLOW.read_text(encoding="utf-8"))
    steps = build["jobs"]["build-uplugin"]["steps"]

    assert not any(str(step.get("uses", "")).startswith("actions/setup-python@") for step in steps)

    setup_step = next(step for step in steps if step.get("name") == "Set up Python")
    assert "python.org/ftp/python" in setup_step["run"]
    assert "python-$pythonVersion-embed-amd64.zip" in setup_step["run"]
    assert "PYTHON_HOME=$installDir" in setup_step["run"]

    run_text = "\n".join(str(step.get("run", "")) for step in steps)
    assert '& "$env:PYTHON_HOME\\python.exe" -m pip install -e ".[dev]"' in run_text
    assert '& "$env:PYTHON_HOME\\python.exe" -m pytest' in run_text
    assert '& "$env:PYTHON_HOME\\python.exe" packaging/build_distributable.py' in run_text
    assert '--python "$env:PYTHON_HOME\\python.exe"' in run_text

    build_text = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_call:" in build_text
    assert "CORE_VERSION: ${{ inputs.core_version || github.event.inputs.core_version || 'latest' }}" in build_text


def test_manual_tag_recovery_rebuilds_assets_without_republishing_pypi() -> None:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    manual_tag = "github.event_name == 'workflow_dispatch' && github.event.inputs.tag_name != ''"

    assert (
        "github.event_name == 'workflow_dispatch' && github.event.inputs.tag_name == ''"
        in (jobs["release-please"]["if"])
    )
    assert manual_tag not in jobs["publish"]["if"]
    assert manual_tag in jobs["attach-release-assets"]["if"]
    assert "needs.publish.result == 'skipped'" in jobs["attach-release-assets"]["if"]

    attach_step = next(
        step for step in jobs["attach-release-assets"]["steps"] if step.get("name") == "Attach wheels to GitHub Release"
    )
    tag_expression = attach_step["with"]["tag_name"]
    assert "github.event.inputs.tag_name" in tag_expression
    assert tag_expression.index("github.event.inputs.tag_name") < tag_expression.index("github.ref_name")
    download_step = next(
        step for step in jobs["attach-release-assets"]["steps"] if step.get("name") == "Download Unreal plugin package"
    )
    assert download_step["with"]["pattern"] == "DccMcpUnreal-*"


def test_release_builds_pythonless_standalone_sidecars() -> None:
    jobs = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    standalone = jobs["standalone"]
    matrix = standalone["strategy"]["matrix"]["include"]

    assert [entry["asset_suffix"] for entry in matrix] == ["linux-X64", "windows-X64", "macOS-Universal2"]
    assert all(entry["core_asset"].startswith("dcc-mcp-server-") for entry in matrix)
    assert "python tools/build_binary.py --server" in "\n".join(
        str(step.get("run", "")) for step in standalone["steps"]
    )
    download = next(step for step in standalone["steps"] if step.get("name") == "Download native core sidecar")
    assert "gh release list --repo dcc-mcp/dcc-mcp-core" in download["run"]
    assert "No recent dcc-mcp-core release contains" in download["run"]
    assert jobs["attach-release-assets"]["needs"] == ["release-please", "publish", "build-unreal-plugin", "standalone"]


def test_standalone_archive_contains_installation_readme() -> None:
    builder = STANDALONE_BUILDER.read_text(encoding="utf-8")
    readme = STANDALONE_README.read_text(encoding="utf-8")

    assert 'shutil.copy2(README, OUTPUT / "README.md")' in builder
    assert "system\nPython installation is not required" in readme
    assert "DCC_MCP_SERVER_EXECUTABLE" in readme
    assert "SHA256SUMS" in readme


def test_standalone_bundles_core_for_native_tool_discovery() -> None:
    config = PYOXIDIZER_CONFIG.read_text(encoding="utf-8")

    assert 'exe.pip_install(["."])' in config


def test_ci_supports_python_39_and_newer() -> None:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    versions = workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"]

    assert versions == ["3.9", "3.10", "3.11", "3.12"]


def test_pythonless_installer_is_fixed_to_official_assets_and_verifies_hashes() -> None:
    installer = STANDALONE_INSTALLER.read_text(encoding="utf-8")

    assert '$repo = "dcc-mcp/dcc-mcp-unreal"' in installer
    assert "Get-FileHash" in installer
    assert "DCC_MCP_SERVER_EXECUTABLE" in installer
    assert "python " not in installer.lower()
    assert "pip " not in installer.lower()
