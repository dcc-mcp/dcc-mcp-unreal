"""Contract tests only: fake reflection is not native Unreal acceptance."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from dcc_mcp_unreal import pcg_capabilities


def _unexpected(*args, **kwargs):
    pytest.fail("Capability inspection must not construct objects or execute authoring methods")


def _host(version="5.8.4-123456+++UE5+Release-5.8"):
    host = SimpleNamespace(SystemLibrary=SimpleNamespace(get_engine_version=lambda: version))
    for surface in pcg_capabilities._SURFACES.values():
        for name, methods in surface.items():
            setattr(host, name, type(name, (), {"__init__": _unexpected, **{method: _unexpected for method in methods}}))
    return host


def _load_skill():
    path = Path("src/dcc_mcp_unreal/skills/unreal-pcg/scripts/inspect_pcg_capabilities.py")
    spec = importlib.util.spec_from_file_location("_test_inspect_pcg", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_complete_python_surface_is_available_but_never_execution_verified():
    result = pcg_capabilities.collect_pcg_capabilities(_host())

    assert all(feature["python_surface_status"] == "available" for feature in result["features"].values())
    assert result["engine"]["version_components"] == [5, 8, 4]
    assert result["engine"]["used_as_feature_gate"] is False
    assert result["execution_verified"] is False
    assert result["native_bridge_verified"] is False
    assert all(feature["execution_verified"] is False for feature in result["features"].values())
    assert result["official_mcp"]["status"] == "unknown"
    assert result["official_mcp"]["tool_schemas"] == "not_queried"
    json.dumps(result)


@pytest.mark.parametrize("version", ["5.2.0", "5.8.4", "6.0.0", "custom-build", None])
def test_version_never_substitutes_for_actual_api_presence(version):
    host = _host(version)
    del host.PCGPathfindingSettings
    del host.PCGPathfindingCostFunctionMode
    host.PCGGraph.add_edge = None

    result = pcg_capabilities.collect_pcg_capabilities(host)

    assert result["features"]["pathfinding"]["python_surface_status"] == "unavailable"
    assert result["features"]["graph"]["python_surface_status"] == "partial"
    assert result["features"]["graph"]["checks"]["PCGGraph.add_edge"]["status"] == "unavailable"
    assert result["execution_verified"] is False


def test_no_plugin_metadata_is_unknown_not_assumed_missing():
    result = pcg_capabilities.collect_pcg_capabilities(SimpleNamespace())

    assert result["engine"]["status"] == "unknown"
    assert all(feature["python_surface_status"] == "unavailable" for feature in result["features"].values())
    for plugin in result["plugins"].values():
        assert plugin["installed"] is None
        assert plugin["enabled"] is None
        assert plugin["discovered"] is None
        assert plugin["reasons"]


def test_registry_descriptor_and_enabled_evidence_are_independent(tmp_path):
    pcg = tmp_path / "PCG.uplugin"
    pcg.write_text("{}")
    missing = tmp_path / "PCGToolset.uplugin"
    queried = []

    def descriptor(name):
        queried.append(name)
        return {"PCG": str(pcg), "PCGToolset": str(missing)}.get(name)

    host = _host()
    host.PluginBlueprintLibrary = SimpleNamespace(
        get_enabled_plugin_names=lambda: ["PCGToolset", "Unrelated"],
        get_plugin_descriptor_file_path=descriptor,
    )
    result = pcg_capabilities.collect_pcg_capabilities(host)

    assert queried == ["PCG", "PCGToolset", "ModelContextProtocol"]
    assert result["plugins"]["PCG"]["installed"] is True
    assert result["plugins"]["PCG"]["enabled"] is False
    assert result["plugins"]["PCGToolset"]["installed"] is False
    assert result["plugins"]["PCGToolset"]["enabled"] is True
    assert result["plugins"]["ModelContextProtocol"]["discovered"] is False
    assert result["plugins"]["ModelContextProtocol"]["installed"] is None
    assert pcg.read_text() == "{}"
    assert not missing.exists()


@pytest.mark.parametrize("names", [None, "PCG", 42])
def test_malformed_plugin_list_does_not_report_disabled(names):
    host = _host()
    host.PluginBlueprintLibrary = SimpleNamespace(
        get_enabled_plugin_names=lambda: names,
        get_plugin_descriptor_file_path=lambda name: 123,
    )
    result = pcg_capabilities.collect_pcg_capabilities(host)
    for plugin in result["plugins"].values():
        assert plugin["enabled"] is None
        assert plugin["installed"] is None
        assert plugin["discovered"] is None


def test_metadata_errors_are_bounded_and_do_not_prevent_surface_inspection():
    def broken(*args):
        raise RuntimeError("x" * 1000)

    host = _host()
    host.SystemLibrary.get_engine_version = broken
    host.PluginBlueprintLibrary = SimpleNamespace(
        get_enabled_plugin_names=broken, get_plugin_descriptor_file_path=broken
    )
    result = pcg_capabilities.collect_pcg_capabilities(host)

    assert result["engine"]["status"] == "unknown"
    assert len(result["engine"]["reason"]) <= 400
    assert result["features"]["graph"]["python_surface_status"] == "available"
    assert all(len(reason) <= 400 for plugin in result["plugins"].values() for reason in plugin["reasons"])


def test_optional_property_probe_does_not_invoke_descriptor():
    class NeverRead:
        def __get__(self, obj, owner=None):
            pytest.fail("Do not evaluate reflected settings properties")

    host = _host()
    host.PCGPathfindingSettings.goal_mapping_mode = NeverRead()
    result = pcg_capabilities.collect_pcg_capabilities(host)
    assert result["features"]["pathfinding"]["optional_properties"]["goal_mapping_mode"]["status"] == "available"


def test_wrong_class_or_noncallable_member_is_not_available():
    host = _host()
    host.PCGGraphFactory = "not a class"
    host.PCGGraph.add_edge = "not a method"
    result = pcg_capabilities.collect_pcg_capabilities(host)
    checks = result["features"]["graph"]["checks"]
    assert checks["PCGGraphFactory"]["status"] == "unavailable"
    assert checks["PCGGraph.add_edge"]["status"] == "unavailable"


def test_inspection_unknown_on_static_lookup_error(monkeypatch):
    original = pcg_capabilities.inspect.getattr_static

    def lookup(owner, name):
        if name == "PCGGraph":
            raise RuntimeError("reflection unavailable")
        return original(owner, name)

    monkeypatch.setattr(pcg_capabilities.inspect, "getattr_static", lookup)
    result = pcg_capabilities.collect_pcg_capabilities(_host())
    assert result["features"]["graph"]["checks"]["PCGGraph"]["status"] == "unknown"


def test_skill_import_is_lazy_and_missing_unreal_returns_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "unreal", None)
    skill = _load_skill()
    result = skill.inspect_pcg_capabilities()
    assert result["success"] is False
    assert "Unreal Python API is unavailable" in str(result)


def test_skill_wraps_observations_without_world_or_http_requests(monkeypatch):
    import urllib.request

    monkeypatch.setitem(sys.modules, "unreal", _host())
    monkeypatch.setattr(urllib.request, "urlopen", _unexpected)
    result = _load_skill().inspect_pcg_capabilities()
    assert result["success"] is True
    assert result["context"]["execution_verified"] is False
    assert result["context"]["schema_version"] == 1


def test_tool_schema_is_read_only_and_main_thread_affine():
    manifest = yaml.safe_load(Path("src/dcc_mcp_unreal/skills/unreal-pcg/tools.yaml").read_text())
    tool = next(tool for tool in manifest["tools"] if tool["name"] == "inspect_pcg_capabilities")
    assert tool["read_only"] is True
    assert tool["destructive"] is False
    assert tool["idempotent"] is True
    assert tool["affinity"] == "main"
    assert tool["enforce_thread_affinity"] is True
    assert tool["input_schema"]["properties"] == {}
