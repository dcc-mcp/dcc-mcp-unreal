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

    assert [entry["ue_version"] for entry in matrix] == ["5.7", "5.8", "4.18"]
    assert matrix[1]["ue_root"] == r"C:\Program Files\Epic Games\UE_5.8"
    assert all("vctoolchain_version" not in entry for entry in matrix)


def test_ue418_native_bridge_uses_the_core_sidecar_wire_contract() -> None:
    module = PLUGIN_MODULE.read_text(encoding="utf-8")
    rules = PLUGIN_RULES.read_text(encoding="utf-8")

    assert "qtserver://127.0.0.1:" in module
    assert "dcc-mcp-server.exe" in module
    for action in ("list_actors", "spawn_actor", "delete_actor", "get_actor_transform", "set_actor_transform"):
        assert f"unreal_actors__{action}" in module
    assert "unreal_level__get_level_info" in module
    assert all(dependency in rules for dependency in ('"Json"', '"Networking"', '"Sockets"', '"UnrealEd"'))


def test_latest_core_fallback_uses_the_newest_available_pypi_wheel() -> None:
    text = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert '$requirement = "dcc-mcp-core-semantic"' in text
    assert '$requirement = "dcc-mcp-core-semantic==$pipVersion"' in text
    assert "pip download $requirement" in text
    assert "$latestTag = gh release view" not in text


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
    for job_name in ("build", "build-unreal-plugin", "standalone", "publish", "attach-release-assets"):
        assert tag_push in jobs[job_name]["if"]
        assert "github.event_name == 'push' ||" not in jobs[job_name]["if"]


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

    build_text = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_call:" in build_text
    assert "CORE_VERSION: ${{ inputs.core_version || github.event.inputs.core_version || 'latest' }}" in build_text


def test_manual_tag_recovery_publishes_and_attaches_to_requested_release() -> None:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    manual_tag = "github.event_name == 'workflow_dispatch' && github.event.inputs.tag_name != ''"

    assert (
        "github.event_name == 'workflow_dispatch' && github.event.inputs.tag_name == ''"
        in (jobs["release-please"]["if"])
    )
    assert manual_tag in jobs["publish"]["if"]
    assert manual_tag in jobs["attach-release-assets"]["if"]

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
    assert jobs["attach-release-assets"]["needs"] == ["release-please", "publish", "build-unreal-plugin", "standalone"]


def test_ci_supports_python_310_and_newer() -> None:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    versions = workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"]

    assert versions == ["3.10", "3.11", "3.12"]


def test_pythonless_installer_is_fixed_to_official_assets_and_verifies_hashes() -> None:
    installer = STANDALONE_INSTALLER.read_text(encoding="utf-8")

    assert '$repo = "dcc-mcp/dcc-mcp-unreal"' in installer
    assert "Get-FileHash" in installer
    assert "DCC_MCP_SERVER_EXECUTABLE" in installer
    assert "python " not in installer.lower()
    assert "pip " not in installer.lower()
