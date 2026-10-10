from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_build_package_module():
    script = (
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_unreal"
        / "skills"
        / "unreal-build-package"
        / "scripts"
        / "_build_package.py"
    )
    spec = importlib.util.spec_from_file_location("_test_build_package", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_build_distributable_module():
    script = Path(__file__).parents[1] / "packaging" / "build_distributable.py"
    spec = importlib.util.spec_from_file_location("_test_build_distributable", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_build_plugin_module():
    script = Path(__file__).parents[1] / "packaging" / "build_plugin.py"
    spec = importlib.util.spec_from_file_location("_test_build_plugin", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_engine(tmp_path: Path) -> Path:
    engine = tmp_path / "UE_5.8"
    (engine / "Engine" / "Build" / "BatchFiles").mkdir(parents=True)
    (engine / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat").write_text("@echo off\n", encoding="utf-8")
    python = engine / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Win64" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    prerequisites = engine / "Engine" / "Extras" / "Redist" / "en-us"
    prerequisites.mkdir(parents=True)
    (prerequisites / "vc_redist.x64.exe").write_bytes(b"redist")
    return engine


def test_local_core_version_must_meet_plugin_minimum(tmp_path):
    module = _load_build_plugin_module()
    core = tmp_path / "dcc-mcp-core"
    core.mkdir()
    (core / "pyproject.toml").write_text('[project]\nversion = "0.19.60"\n', encoding="utf-8")

    try:
        module.validate_local_core(core)
    except ValueError as exc:
        assert "0.20.13" in str(exc)
    else:
        raise AssertionError("stale local core must be rejected")


def test_build_plugin_package_reuses_repository_build_script(tmp_path, monkeypatch):
    module = _load_build_package_module()
    repository = tmp_path / "repo"
    script = repository / "packaging" / "build_distributable.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    engine = _make_engine(tmp_path)
    observed = {}

    def fake_run(command, cwd, log_path):
        observed["command"] = command
        observed["cwd"] = cwd
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("ok", encoding="utf-8")
        archive = repository / "dist" / "DccMcpUnreal-0.2.0-ue5.8-win64.zip"
        archive.write_bytes(b"zip")
        return 0

    monkeypatch.setattr(module, "_run_logged", fake_run)

    result = module.build_plugin_package_impl(str(repository), str(engine))

    assert result["success"] is True
    assert observed["cwd"] == repository.resolve()
    assert observed["command"][1] == str(script.resolve())
    assert "--mode" in observed["command"]
    assert result["context"]["archive_path"].endswith("ue5.8-win64.zip")


def test_legacy_ubt_user_config_is_restored_after_build_failure(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    appdata = tmp_path / "appdata"
    config = appdata / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"
    config.parent.mkdir(parents=True)
    original = (
        b"<Configuration><WindowsPlatform><CompilerVersion>14.36</CompilerVersion></WindowsPlatform></Configuration>"
    )
    config.write_bytes(original)
    monkeypatch.setenv("APPDATA", str(appdata))

    try:
        with module.temporarily_clear_legacy_ubt_user_config(tmp_path / "work"):
            assert b"CompilerVersion" not in config.read_bytes()
            raise RuntimeError("simulated UAT failure")
    except RuntimeError:
        pass

    assert config.read_bytes() == original
    assert not (tmp_path / "work" / "legacy-ubt-user-BuildConfiguration.xml.backup").exists()


def test_legacy_ubt_config_guard_wraps_only_the_uat_subprocess():
    module = _load_build_distributable_module()

    assert "temporarily_clear_legacy_ubt_user_config" in inspect.getsource(module.build_precompiled_plugin)
    assert "temporarily_clear_legacy_ubt_user_config" not in inspect.getsource(module.build_python_payload)


def test_explicit_compiler_is_required_even_when_no_toolchains_are_discovered(monkeypatch):
    module = _load_build_distributable_module()
    monkeypatch.setattr(module, "_msvc_toolchain_roots", lambda: [])
    with pytest.raises(RuntimeError, match="Requested MSVC 14.36"):
        module._check_msvc_toolchain("14.36")


def test_compiler_prefix_has_a_version_boundary_and_requires_cl(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    wrong = tmp_path / "14.360.10000"
    compiler = wrong / "bin" / "Hostx64" / "x64" / "cl.exe"
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(b"compiler")
    missing = tmp_path / "14.36.32532"
    missing.mkdir()
    monkeypatch.setattr(module, "_msvc_toolchain_roots", lambda: [wrong, missing])
    with pytest.raises(RuntimeError):
        module._check_msvc_toolchain("14.36")
    compiler = missing / "bin" / "Hostx64" / "x64" / "cl.exe"
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(b"compiler")
    module._check_msvc_toolchain("14.36")


def test_vswhere_handles_custom_installations_and_editions(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    vswhere = tmp_path / "vswhere.exe"
    vswhere.touch()
    installation = tmp_path / "custom Enterprise"
    tools = installation / "VC" / "Tools" / "MSVC" / "14.44.35207"
    tools.mkdir(parents=True)
    monkeypatch.setattr(module.shutil, "which", lambda _command: str(vswhere))
    calls = []

    def discover(command, **_kwargs):
        calls.append(command)
        return json.dumps([{"installationPath": str(installation)}])

    monkeypatch.setattr(module.subprocess, "check_output", discover)
    assert module._msvc_toolchain_roots() == [tools]
    assert "-products" in calls[0] and "*" in calls[0]


def test_ubt_selection_must_match_every_compiled_target(tmp_path):
    module = _load_build_distributable_module()
    log = tmp_path / "uat.log"
    good = "Using Visual Studio 2022 14.36.32532 toolchain (C:/VS) and Windows 10.0.22621.0 SDK (C:/Kits).\n"
    log.write_text(good, encoding="utf-8")
    module.verify_ubt_toolchain(log, "14.36", "10.0.22621.0")
    with pytest.raises(RuntimeError, match="selected compiler"):
        module.verify_ubt_toolchain(log, "14.44", "")
    log.write_text(good + good.replace("14.36", "14.44"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="selected compiler"):
        module.verify_ubt_toolchain(log, "14.36", "")
    log.write_text("UAT succeeded without selection evidence", encoding="utf-8")
    with pytest.raises(RuntimeError, match="did not report"):
        module.verify_ubt_toolchain(log, "14.36", "")


def test_legacy_config_recovers_backup_after_process_death(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config = tmp_path / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"
    config.parent.mkdir(parents=True)
    original = b"user settings"
    backup = config.with_name("BuildConfiguration.xml.dcc-mcp-backup")
    backup.write_bytes(original)
    config.write_bytes(module.EMPTY_UBT_CONFIG)
    with module.temporarily_clear_legacy_ubt_user_config(tmp_path / "work"):
        assert backup.read_bytes() == original
    assert config.read_bytes() == original
    assert not backup.exists()


def test_orphaned_absence_marker_never_deletes_a_later_user_configuration(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config = tmp_path / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"
    config.parent.mkdir(parents=True)
    original = b"user configuration created after interrupted restore"
    config.write_bytes(original)
    marker = config.with_name("BuildConfiguration.xml.dcc-mcp-created")
    marker.touch()
    config.with_name("BuildConfiguration.xml.dcc-mcp-active").write_bytes(module.EMPTY_UBT_CONFIG)
    with module.temporarily_clear_legacy_ubt_user_config(tmp_path / "work"):
        assert config.with_name("BuildConfiguration.xml.dcc-mcp-backup").read_bytes() == original
        assert not marker.exists()
    assert config.read_bytes() == original


def test_interrupted_restore_of_absent_original_keeps_configuration_absent(tmp_path):
    module = _load_build_distributable_module()
    config = tmp_path / "BuildConfiguration.xml"
    config.with_name("BuildConfiguration.xml.dcc-mcp-created").touch()
    config.with_name("BuildConfiguration.xml.dcc-mcp-backup").write_bytes(b"")
    config.with_name("BuildConfiguration.xml.dcc-mcp-active").write_bytes(module.EMPTY_UBT_CONFIG)
    # The prior restore had already removed its created configuration.
    module.recover_legacy_ubt_user_config(config)
    assert not config.exists()
    assert not config.with_name("BuildConfiguration.xml.dcc-mcp-created").exists()
    assert not config.with_name("BuildConfiguration.xml.dcc-mcp-backup").exists()


def test_legacy_config_preserves_external_edits_and_original_backup(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config = tmp_path / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"original")
    with pytest.raises(RuntimeError, match="original preserved"):
        with module.temporarily_clear_legacy_ubt_user_config(tmp_path / "work"):
            config.write_bytes(b"external edit")
    assert config.read_bytes() == b"external edit"
    assert config.with_name("BuildConfiguration.xml.dcc-mcp-backup").read_bytes() == b"original"


def test_ubt_lock_excludes_another_process(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    script = Path(module.__file__)
    child = (
        "import importlib.util; "
        "s=importlib.util.spec_from_file_location('builder', {!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "m.ubt_user_config_lock(timeout=0.2).__enter__()"
    ).format(str(script))
    with module.ubt_user_config_lock():
        result = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Another UAT job owns" in result.stderr


def test_toolset_family_and_compiler_patch_are_recorded_separately(tmp_path):
    module = _load_build_distributable_module()
    log = tmp_path / "uat.log"
    log.write_text(
        "Using Visual Studio 2022 14.44.35225 toolchain (C:\\Program Files (x86)\\VS\\VC\\Tools\\MSVC\\14.44.35207) "
        "and Windows 10.0.26100.0 SDK (C:\\Kits).",
        encoding="utf-8",
    )
    module.verify_ubt_toolchain(log, "14.44.35207", "10.0.26100.0")
    with pytest.raises(RuntimeError, match="selected compiler"):
        module.verify_ubt_toolchain(log, "14.44.35225", "")


def test_legacy_xml_selection_is_scoped_and_removes_previously_absent_config(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config = tmp_path / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"
    with module.temporarily_clear_legacy_ubt_user_config(tmp_path / "work", "14.36", "10.0.19041.0"):
        xml = config.read_text(encoding="utf-8")
        assert "<CompilerVersion>14.36</CompilerVersion>" in xml
        assert "<WindowsSdkVersion>10.0.19041.0</WindowsSdkVersion>" in xml
    assert not config.exists()


def test_legacy_engine_compiler_pin_accepts_reported_windows_sdk_81(tmp_path):
    module = _load_build_distributable_module()
    log = tmp_path / "uat.log"
    log.write_text(
        "Using Visual Studio 2017 14.16.27048 toolchain (C:/VS/VC/Tools/MSVC/14.16.27023) "
        "and Windows 8.1 SDK (C:/Kits).",
        encoding="utf-8",
    )
    module.verify_ubt_toolchain(log, "14.16", "")


def test_buildplugin_uses_native_ubt_argument_contract_and_restores_it(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    engine = _make_engine(tmp_path)
    entrypoint = engine / "Engine" / "Source" / "Programs" / "UnrealBuildTool" / "UnrealBuildTool.cs"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text('Environment.GetEnvironmentVariable("UBT_EXTRA_ARGS")', encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("UBT_EXTRA_ARGS", "-NoUBA")
    monkeypatch.setattr(module, "_check_msvc_toolchain", lambda _version: None)
    observed = []

    def fake_uat(command, **_kwargs):
        observed.append(module.os.environ["UBT_EXTRA_ARGS"])
        assert not any(arg.startswith("-ubtargs=") for arg in command)

    monkeypatch.setattr(module, "run", fake_uat)
    monkeypatch.setattr(module, "verify_ubt_toolchain", lambda *_args: None)
    module.build_precompiled_plugin(
        SimpleNamespace(
            ue_root=engine, vctoolchain_version="14.36", sdk_version="10.0.19041.0", patched_headers_dir=""
        ),
        tmp_path / "uat",
    )
    assert "-NoUBA -CompilerVersion=14.36 -WindowsSdkVersion=10.0.19041.0" in observed[0]
    assert module.os.environ["UBT_EXTRA_ARGS"] == "-NoUBA"


def test_ue58_in_place_update_uses_job_scoped_generated_header_aliases(tmp_path):
    module = _load_build_distributable_module()
    engine = tmp_path / "UE_5.8"
    build_dir = engine / "Engine" / "Build"
    build_dir.mkdir(parents=True)
    (build_dir / "Build.version").write_text(
        json.dumps({"MajorVersion": 5, "MinorVersion": 8, "PatchVersion": 1}),
        encoding="utf-8",
    )
    source = engine / "Engine" / "Source" / "Runtime" / "CoreUObject" / "Public" / "UObject" / "Package.h"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            ["// filler"] * 214
            + [
                "UCLASS(MinimalAPI, Config=Engine)",
                "class UPackage : public UObject",
                "{",
                "    GENERATED_BODY()",
                "};",
            ]
        ),
        encoding="utf-8",
    )
    generated = (
        engine
        / "Engine"
        / "Intermediate"
        / "Build"
        / "Win64"
        / "UnrealEditor"
        / "Inc"
        / "CoreUObject"
        / "UHT"
        / "Package.generated.h"
    )
    generated.parent.mkdir(parents=True)
    generated.write_text(
        "#define FID_Engine_Source_Runtime_CoreUObject_Public_UObject_Package_h_214_PROLOG\n"
        "#define FID_Engine_Source_Runtime_CoreUObject_Public_UObject_Package_h_217_GENERATED_BODY\n",
        encoding="utf-8",
    )

    compat = module.create_generated_header_compat(engine, tmp_path / "work")

    assert compat is not None
    text = compat.read_text(encoding="utf-8")
    assert "Package_h_215_PROLOG FID_Engine_Source_Runtime_CoreUObject_Public_UObject_Package_h_214_PROLOG" in text
    assert (
        "Package_h_218_GENERATED_BODY "
        "FID_Engine_Source_Runtime_CoreUObject_Public_UObject_Package_h_217_GENERATED_BODY" in text
    )


def test_matching_ue58_generated_headers_need_no_compatibility_file(tmp_path):
    module = _load_build_distributable_module()
    engine = tmp_path / "UE_5.8"
    build_dir = engine / "Engine" / "Build"
    build_dir.mkdir(parents=True)
    (build_dir / "Build.version").write_text(
        json.dumps({"MajorVersion": 5, "MinorVersion": 8, "PatchVersion": 1}),
        encoding="utf-8",
    )
    source = engine / "Engine" / "Source" / "Runtime" / "CoreUObject" / "Public" / "UObject" / "Package.h"
    source.parent.mkdir(parents=True)
    source.write_text(
        "UCLASS(MinimalAPI, Config=Engine)\nclass UPackage\n{\n    GENERATED_BODY()\n};\n",
        encoding="utf-8",
    )
    generated = (
        engine
        / "Engine"
        / "Intermediate"
        / "Build"
        / "Win64"
        / "UnrealEditor"
        / "Inc"
        / "CoreUObject"
        / "UHT"
        / "Package.generated.h"
    )
    generated.parent.mkdir(parents=True)
    generated.write_text(
        "#define FID_Engine_Source_Runtime_CoreUObject_Public_UObject_Package_h_1_PROLOG\n"
        "#define FID_Engine_Source_Runtime_CoreUObject_Public_UObject_Package_h_4_GENERATED_BODY\n",
        encoding="utf-8",
    )

    assert module.create_generated_header_compat(engine, tmp_path / "work") is None


def test_ue4_native_payload_skips_incompatible_embedded_python_dependencies(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    engine = tmp_path / "UE_4.26"
    build_dir = engine / "Engine" / "Build"
    build_dir.mkdir(parents=True)
    (build_dir / "Build.version").write_text(
        json.dumps({"MajorVersion": 4, "MinorVersion": 26}),
        encoding="utf-8",
    )
    observed = []
    monkeypatch.setattr(module, "run", lambda command: observed.append(command))

    module.build_python_payload(
        SimpleNamespace(
            core_wheel=None,
            core_wheel_url=None,
            work_dir=tmp_path / "work",
            ue_root=engine,
            python=None,
            python_plugin_name="PythonScriptPlugin",
            mode="native",
            skip_core=False,
            use_local_core=False,
            core_root=tmp_path / "core",
            core_spec="dcc-mcp-core>=0.20.0,<1.0.0",
        ),
        tmp_path / "payload",
    )

    assert "--skip-python-deps" in observed[0]


def test_ue4_source_engine_allows_uat_to_compile(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    engine = tmp_path / "UE_4.26"
    batch_files = engine / "Engine" / "Build" / "BatchFiles"
    batch_files.mkdir(parents=True)
    (batch_files / "RunUAT.bat").write_text("@echo off\n", encoding="utf-8")
    (engine / "Engine" / "Build" / "Build.version").write_text(
        json.dumps({"MajorVersion": 4, "MinorVersion": 26}),
        encoding="utf-8",
    )
    for project in ("AutomationTool", "AutomationToolLauncher"):
        project_dir = engine / "Engine" / "Source" / "Programs" / project
        project_dir.mkdir(parents=True)
        (project_dir / "{}.csproj".format(project)).write_text("", encoding="utf-8")

    observed = []
    monkeypatch.setattr(module, "run", lambda command: observed.append(command))
    monkeypatch.setattr(module, "_check_msvc_toolchain", lambda version: None)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    module.build_precompiled_plugin(
        SimpleNamespace(
            ue_root=engine,
            vctoolchain_version="",
            patched_headers_dir="",
        ),
        tmp_path / "uat" / "DccMcpUnreal",
    )

    assert "-nocompile" not in observed[0]


def test_ue4_installed_engine_uses_precompiled_uat(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    engine = tmp_path / "UE_4.26"
    batch_files = engine / "Engine" / "Build" / "BatchFiles"
    batch_files.mkdir(parents=True)
    (batch_files / "RunUAT.bat").write_text("@echo off\n", encoding="utf-8")
    (engine / "Engine" / "Build" / "Build.version").write_text(
        json.dumps({"MajorVersion": 4, "MinorVersion": 26}),
        encoding="utf-8",
    )
    for project in ("AutomationTool", "AutomationToolLauncher"):
        project_dir = engine / "Engine" / "Source" / "Programs" / project
        project_dir.mkdir(parents=True)
        (project_dir / "{}.csproj".format(project)).write_text("", encoding="utf-8")
    automation_tool = engine / "Engine" / "Binaries" / "DotNET" / "AutomationTool.exe"
    automation_tool.parent.mkdir(parents=True)
    automation_tool.write_bytes(b"")

    observed = []
    monkeypatch.setattr(module, "run", lambda command: observed.append(command))
    monkeypatch.setattr(module, "_check_msvc_toolchain", lambda version: None)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    module.build_precompiled_plugin(
        SimpleNamespace(
            ue_root=engine,
            vctoolchain_version="",
            patched_headers_dir="",
        ),
        tmp_path / "uat" / "DccMcpUnreal",
    )

    assert "-nocompile" in observed[0]


def test_package_project_executable_builds_fixed_uat_command(tmp_path, monkeypatch):
    module = _load_build_package_module()
    engine = _make_engine(tmp_path)
    project = tmp_path / "Game" / "Game.uproject"
    project.parent.mkdir()
    project.write_text("{}", encoding="utf-8")
    output = tmp_path / "Builds" / "Game-Win64"
    observed = {}

    def fake_run(command, cwd, log_path):
        observed["command"] = command
        observed["cwd"] = cwd
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("ok", encoding="utf-8")
        executable = output / "Windows" / "Game.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"exe")
        return 0

    monkeypatch.setattr(module, "_run_logged", fake_run)

    result = module.package_project_executable_impl(
        str(project),
        str(output),
        ue_root=str(engine),
        configuration="Shipping",
    )

    assert result["success"] is True
    assert observed["cwd"] == project.parent.resolve()
    assert "-clientconfig=Shipping" in observed["command"]
    assert "-package" in observed["command"]
    assert "-archive" in observed["command"]
    assert "-prereqs" in observed["command"]
    assert "-archivedirectory={}".format(output.resolve()) in observed["command"]
    assert result["context"]["executable_paths"] == [str(output.resolve() / "Windows" / "Game.exe")]


def test_package_project_executable_builds_installer_and_steam_profiles(tmp_path, monkeypatch):
    module = _load_build_package_module()
    engine = _make_engine(tmp_path)
    project = tmp_path / "Game" / "Game.uproject"
    project.parent.mkdir()
    project.write_text("{}", encoding="utf-8")
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"compiler")
    commands = []

    def fake_run(command, cwd, log_path):
        commands.append(command)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("ok", encoding="utf-8")
        if command[0] == str(compiler.resolve()):
            installer = tmp_path / "InstallerBuild" / "Installer" / "Test-Game-Setup-2.0.0.exe"
            installer.parent.mkdir(parents=True, exist_ok=True)
            installer.write_bytes(b"setup")
        else:
            output_name = "InstallerBuild" if "InstallerBuild" in command[-2] else "SteamBuild"
            executable = tmp_path / output_name / "Windows" / "Game.exe"
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_bytes(b"game")
        return 0

    monkeypatch.setattr(module, "_run_logged", fake_run)
    installer_result = module.package_project_executable_impl(
        str(project),
        str(tmp_path / "InstallerBuild"),
        ue_root=str(engine),
        release_profile="installer",
        product_name="Test Game",
        product_version="2.0.0",
        installer_compiler_path=str(compiler),
    )
    steam_result = module.package_project_executable_impl(
        str(project),
        str(tmp_path / "SteamBuild"),
        ue_root=str(engine),
        release_profile="steam",
        steam_app_id="123456",
        steam_depot_id="123457",
    )

    assert installer_result["success"] is True
    assert (tmp_path / "InstallerBuild" / "Installer" / "Test-Game-Setup-2.0.0.exe").is_file()
    installer_script = (tmp_path / "InstallerBuild" / "Installer" / "game-installer.iss").read_text(
        encoding="utf-8-sig"
    )
    assert "VersionInfoVersion=2.0.0.0" in installer_script
    assert "UE4PrereqSetup_x64.exe" in installer_script
    assert steam_result["success"] is True
    app_vdf = tmp_path / "SteamBuild" / "SteamPipe" / "scripts" / "app_build_123456.vdf"
    assert '"Preview" "1"' in app_vdf.read_text(encoding="utf-8")
    assert '"123457" "depot_build_123457.vdf"' in app_vdf.read_text(encoding="utf-8")
    assert "-prereqs" not in commands[-1]


def test_wegame_profile_writes_preflight_manifest(tmp_path, monkeypatch):
    module = _load_build_package_module()
    engine = _make_engine(tmp_path)
    project = tmp_path / "Game" / "Game.uproject"
    project.parent.mkdir()
    project.write_text("{}", encoding="utf-8")
    output = tmp_path / "WeGameBuild"

    def fake_run(command, cwd, log_path):
        executable = output / "Windows" / "Game.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"game")
        return 0

    monkeypatch.setattr(module, "_run_logged", fake_run)
    result = module.package_project_executable_impl(
        str(project),
        str(output),
        ue_root=str(engine),
        release_profile="wegame",
    )

    manifest = json.loads((output / "WeGame" / "release-preflight.json").read_text(encoding="utf-8"))
    assert result["success"] is True
    assert manifest["schema"] == "dcc-mcp-unreal.wegame-preflight.v1"
    assert manifest["content_root"] == "../Windows"
    assert manifest["executable"] == "Game.exe"


def test_package_project_executable_rejects_missing_project(tmp_path):
    module = _load_build_package_module()

    result = module.package_project_executable_impl(
        str(tmp_path / "Missing.uproject"),
        str(tmp_path / "Build"),
        ue_root=str(tmp_path / "UE_5.8"),
    )

    assert result["success"] is False
    assert "Saved .uproject file not found" in result["error"]
