import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BUILD_WORKFLOW = ROOT / ".github" / "workflows" / "build-uplugin.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CONFIGURE_SCRIPT = ROOT / ".github" / "scripts" / "configure-ubt-toolchain.ps1"
BUILD_DISTRIBUTABLE = ROOT / "packaging" / "build_distributable.py"


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
    for workflow in (BUILD_WORKFLOW, RELEASE_WORKFLOW):
        text = workflow.read_text(encoding="utf-8")
        assert ".github/scripts/configure-ubt-toolchain.ps1" in text
        assert "$env:APPDATA" not in text
        assert "DCC_MCP_UNREAL_UBT_APPDATA" not in text


def test_toolchain_script_selects_latest_valid_compiler_for_ue57(
    tmp_path: Path,
) -> None:
    environment = _configure_toolchain("5.7", tmp_path)

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


def test_ue52_workflows_keep_the_supported_cli_toolchain_override() -> None:
    for workflow in (BUILD_WORKFLOW, RELEASE_WORKFLOW):
        text = workflow.read_text(encoding="utf-8")
        assert 'vctoolchain_version: "14.36"' in text
        assert "VCTOOLCHAIN_VERSION: ${{ matrix.vctoolchain_version || '' }}" in text

    packaging = BUILD_DISTRIBUTABLE.read_text(encoding="utf-8")
    assert 'ubtargs.append("-VCToolchainVersion={}"' in packaging


def test_latest_core_fallback_uses_the_newest_available_pypi_wheel() -> None:
    for workflow in (BUILD_WORKFLOW, RELEASE_WORKFLOW):
        text = workflow.read_text(encoding="utf-8")
        assert '$requirement = "dcc-mcp-core-semantic"' in text
        assert '$requirement = "dcc-mcp-core-semantic==$pipVersion"' in text
        assert "pip download $requirement" in text
        assert "$latestTag = gh release view" not in text


def test_release_jobs_run_after_release_please_is_skipped_for_tag_events() -> None:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    for job_name in ("build", "build-unreal-plugin", "publish", "attach-release-assets"):
        assert "always()" in jobs[job_name]["if"]

    assert "needs.build.result == 'success'" in jobs["publish"]["if"]
    assert "needs.publish.result == 'success'" in jobs["attach-release-assets"]["if"]
    assert "needs.build-unreal-plugin.result == 'success'" in jobs["attach-release-assets"]["if"]
