from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "dcc_mcp_unreal"
    / "skills"
    / "unreal-automation"
    / "scripts"
    / "mcp_self_check.py"
)


def _helpers() -> dict:
    return runpy.run_path(str(SCRIPT), run_name="unreal_install_identity_test")


@pytest.mark.parametrize("value", ("5.7", "5.7.0rc1", "garbage5.7.0", "5.7.0.1"))
def test_runtime_engine_version_is_canonical(value: str) -> None:
    with pytest.raises(ValueError, match="noncanonical"):
        _helpers()["_canonical_engine_version"](value)


def test_runtime_identity_binds_live_process_project_plugin_and_origins(monkeypatch, tmp_path: Path) -> None:
    helpers = _helpers()
    editor = tmp_path / "UnrealEditor"
    editor.write_bytes(b"native-editor")
    project = tmp_path / "Sample" / "Sample.uproject"
    project.parent.mkdir()
    project.write_text("{}", encoding="utf-8")
    plugin = project.parent / "Plugins" / "DccMcpUnreal"
    plugin.mkdir(parents=True)
    (plugin / "DccMcpUnreal.uplugin").write_text("{}", encoding="utf-8")
    adapter_origin = tmp_path / "site" / "dcc_mcp_unreal" / "__init__.py"
    core_origin = tmp_path / "site" / "dcc_mcp_core" / "__init__.py"
    adapter_origin.parent.mkdir(parents=True)
    core_origin.parent.mkdir(parents=True)
    adapter_origin.write_text("# adapter\n", encoding="utf-8")
    core_origin.write_text("# core\n", encoding="utf-8")
    adapter_module = types.SimpleNamespace(__file__=str(adapter_origin))
    core_module = types.SimpleNamespace(__file__=str(core_origin))
    init_module = types.SimpleNamespace(PROCESS_START_TOKEN="a" * 32)
    unreal_module = types.SimpleNamespace(
        Paths=types.SimpleNamespace(get_project_file_path=lambda: str(project)),
        PluginBlueprintLibrary=types.SimpleNamespace(get_plugin_base_dir=lambda _name: str(plugin)),
        SystemLibrary=types.SimpleNamespace(get_engine_version=lambda: "5.7.0-release"),
    )
    monkeypatch.setitem(sys.modules, "dcc_mcp_unreal", adapter_module)
    monkeypatch.setitem(sys.modules, "dcc_mcp_core", core_module)
    monkeypatch.setitem(sys.modules, "init_unreal", init_module)
    monkeypatch.setitem(sys.modules, "unreal", unreal_module)
    monkeypatch.setattr(sys, "executable", str(editor))
    monkeypatch.setattr(
        helpers["metadata"],
        "version",
        lambda name: {"dcc-mcp-unreal": "0.3.0", "dcc-mcp-core": "0.20.13"}[name],
    )
    server = types.SimpleNamespace(instance_id="11111111-1111-1111-1111-111111111111")

    identity = helpers["_install_identity"](server)

    assert identity == {
        "instance_id": "11111111-1111-1111-1111-111111111111",
        "host_pid": helpers["os"].getpid(),
        "process_start_token": "a" * 32,
        "editor_executable": str(editor.resolve()),
        "project_file": str(project.resolve()),
        "plugin_root": str(plugin.resolve()),
        "engine_version": "5.7.0",
        "adapter_version": "0.3.0",
        "core_version": "0.20.13",
        "adapter_origin": str(adapter_origin.resolve()),
        "core_origin": str(core_origin.resolve()),
    }
