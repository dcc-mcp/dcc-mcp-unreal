from __future__ import annotations

import importlib.util
import json
from pathlib import Path


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


def test_ue4_user_config_is_restored_after_build_failure(tmp_path, monkeypatch):
    module = _load_build_distributable_module()
    appdata = tmp_path / "appdata"
    config = appdata / "Unreal Engine" / "UnrealBuildTool" / "BuildConfiguration.xml"
    config.parent.mkdir(parents=True)
    original = b"<Configuration><WindowsPlatform><CompilerVersion>14.36</CompilerVersion></WindowsPlatform></Configuration>"
    config.write_bytes(original)
    monkeypatch.setenv("APPDATA", str(appdata))

    try:
        with module.temporarily_clear_ue4_user_config(tmp_path / "work"):
            assert b"CompilerVersion" not in config.read_bytes()
            raise RuntimeError("simulated UAT failure")
    except RuntimeError:
        pass

    assert config.read_bytes() == original
    assert not (tmp_path / "work" / "ue4-user-BuildConfiguration.xml.backup").exists()


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
