from __future__ import annotations

import importlib.util
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


def _make_engine(tmp_path: Path) -> Path:
    engine = tmp_path / "UE_5.8"
    (engine / "Engine" / "Build" / "BatchFiles").mkdir(parents=True)
    (engine / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat").write_text("@echo off\n", encoding="utf-8")
    python = engine / "Engine" / "Binaries" / "ThirdParty" / "Python3" / "Win64" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
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
    assert "-archivedirectory={}".format(output.resolve()) in observed["command"]
    assert result["context"]["executable_paths"] == [str(output.resolve() / "Windows" / "Game.exe")]


def test_package_project_executable_rejects_missing_project(tmp_path):
    module = _load_build_package_module()

    result = module.package_project_executable_impl(
        str(tmp_path / "Missing.uproject"),
        str(tmp_path / "Build"),
        ue_root=str(tmp_path / "UE_5.8"),
    )

    assert result["success"] is False
    assert "Saved .uproject file not found" in result["error"]
