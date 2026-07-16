from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_WORKFLOW = ROOT / ".github" / "workflows" / "build-uplugin.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CONFIGURE_SCRIPT = ROOT / ".github" / "scripts" / "configure-ubt-appdata.ps1"


def test_plugin_workflows_isolate_unrealbuildtool_appdata() -> None:
    for workflow in (BUILD_WORKFLOW, RELEASE_WORKFLOW):
        text = workflow.read_text(encoding="utf-8")
        assert ".github/scripts/configure-ubt-appdata.ps1" in text
        assert "$env:APPDATA = $env:DCC_MCP_UNREAL_UBT_APPDATA" in text


def test_toolchain_script_pins_only_ue52_inside_runner_temp() -> None:
    text = CONFIGURE_SCRIPT.read_text(encoding="utf-8")

    assert 'if ($UEVersion -eq "5.2")' in text
    assert "<CompilerVersion>14.36.32532</CompilerVersion>" in text
    assert "$env:RUNNER_TEMP" in text
    assert '"DCC_MCP_UNREAL_UBT_APPDATA=$appData"' in text
    assert "$env:APPDATA" not in text


def test_build_workflow_no_longer_writes_global_ubt_config() -> None:
    text = BUILD_WORKFLOW.read_text(encoding="utf-8")

    assert '".github/scripts/configure-ubt-appdata.ps1"' in text
    assert '"$env:APPDATA\\Unreal Engine\\UnrealBuildTool"' not in text
    assert "Force MSVC 14.36 toolchain via BuildConfiguration.xml" not in text


def test_release_workflow_declares_ue52_toolchain_version() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert 'vctoolchain_version: "14.36"' in text
    assert "VCTOOLCHAIN_VERSION: ${{ matrix.vctoolchain_version || '' }}" in text
