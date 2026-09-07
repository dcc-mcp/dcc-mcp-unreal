import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dcc_mcp_unreal.asset_details import asset_details, observe
from dcc_mcp_unreal.plugin_configuration import apply_plugin_configuration, plugin_configuration_plan


def test_missing_and_empty_readbacks_are_distinct():
    assert observe("empty", lambda: [])["value"] == []
    result = observe("missing", lambda: 1 / 0)
    assert result["status"] == "unavailable"
    assert "value" not in result


def test_mesh_negative_sentinel_is_not_geometry():
    mesh = NS(
        get_num_lods=lambda: 1,
        get_num_vertices=lambda i: -1,
        get_num_triangles=lambda i: 0,
        get_num_sections=lambda i: 0,
    )
    result = asset_details(NS(), mesh, "StaticMesh")
    assert result["lods"][0]["vertices"]["status"] == "unavailable"
    assert result["lods"][0]["triangles"]["value"] == 0
    assert result["material_slots"]["status"] == "unavailable"
    assert result["wind"]["dynamic_validation"] == "not_performed"


@pytest.fixture
def host(tmp_path):
    project = tmp_path / "Test.uproject"
    project.write_text(json.dumps({"Unrelated": 42, "Plugins": []}))
    plugin = tmp_path / "SpeedTreeImporter.uplugin"
    plugin.write_text(json.dumps({"EnabledByDefault": True}))
    unreal = NS(
        Paths=NS(get_project_file_path=lambda: str(project), convert_relative_path_to_full=lambda p: p),
        PluginBlueprintLibrary=NS(get_plugin_descriptor_file_path=lambda name: str(plugin)),
        DccMcpAutomationLibrary=NS(get_enabled_plugin_names=lambda: ["SpeedTreeImporter"]),
    )
    return unreal, project


def test_inheritance_is_not_disabled_or_loaded(host):
    unreal, _ = host
    row = plugin_configuration_plan(unreal, "speedtree_import")["plugins"][0]
    assert row["project_enabled"] is None
    assert row["enabled_by_default"] is True
    assert row["installed"] is True and row["runtime_enabled"] is True
    assert row["modules_loaded"]["status"] == "unavailable"


def test_unsupported_consent_never_writes(host):
    unreal, project = host
    original = project.read_bytes()
    plan = plugin_configuration_plan(unreal, "speedtree_import")
    result = apply_plugin_configuration(unreal, "speedtree_import", plan["project_sha256"])
    assert result["status"] == "consent_required"
    assert result["reason"] == "elicitation_not_supported"
    assert project.read_bytes() == original
    assert list(project.parent.glob("*.bak")) == []


def test_hash_conflict_fails_before_consent(host, monkeypatch):
    unreal, project = host
    plan = plugin_configuration_plan(unreal, "speedtree_import")
    project.write_text("{}")
    monkeypatch.setattr("dcc_mcp_core.elicitation.elicit_form_sync", lambda *a, **kw: pytest.fail("must not ask"))
    assert apply_plugin_configuration(unreal, "speedtree_import", plan["project_sha256"])["status"] == "conflict"


def test_independent_consent_preserves_backup_and_fields(host, monkeypatch):
    unreal, project = host
    original = project.read_bytes()
    monkeypatch.setattr(
        "dcc_mcp_core.elicitation.elicit_form_sync", lambda *a, **kw: NS(accepted=True, data={"enable_plugins": True})
    )
    plan = plugin_configuration_plan(unreal, "speedtree_import")
    result = apply_plugin_configuration(unreal, "speedtree_import", plan["project_sha256"])
    assert result["status"] == "configured"
    assert Path(result["backup_path"]).read_bytes() == original
    assert json.loads(project.read_text()) == {
        "Unrelated": 42,
        "Plugins": [{"Name": "SpeedTreeImporter", "Enabled": True}],
    }
    assert not list(project.parent.glob("*.lock"))
    assert result["runtime_verified"] is False


def test_change_during_consent_rejects_write(host, monkeypatch):
    unreal, project = host
    plan = plugin_configuration_plan(unreal, "speedtree_import")

    def consent(*args, **kwargs):
        project.write_text("{}")
        return NS(accepted=True, data={"enable_plugins": True})

    monkeypatch.setattr("dcc_mcp_core.elicitation.elicit_form_sync", consent)
    assert apply_plugin_configuration(unreal, "speedtree_import", plan["project_sha256"])["status"] == "conflict"
    assert project.read_text() == "{}"


def test_ue55_vertices_use_subsystem_fallback():
    mesh = NS(get_num_lods=lambda: 1, get_num_triangles=lambda i: 10, get_num_sections=lambda i: 1)
    subsystem = NS(
        get_number_verts=lambda mesh, i: 12,
        get_lod_screen_sizes=lambda mesh: [1.0],
        get_lod_material_slot=lambda mesh, i, s: 2,
    )
    unreal = NS(StaticMeshEditorSubsystem=object, get_editor_subsystem=lambda cls: subsystem)
    result = asset_details(unreal, mesh, "StaticMesh")
    assert result["lods"][0]["vertices"]["value"] == 12
    assert result["lods"][0]["section_material_slots"]["value"] == [2]


def test_get_asset_info_rejects_wrong_object_identity(monkeypatch):
    import sys

    import test_groom_asset_info

    module = test_groom_asset_info._load_module(monkeypatch)
    data = NS(object_path="/Game/Tree.Correct")
    unreal = NS(AssetRegistryHelpers=NS(get_asset_registry=lambda: NS(get_assets_by_package_name=lambda p: [data])))
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    assert module.get_asset_info("/Game/Tree.Wrong")["success"] is False


def test_plugin_configuration_missing_installation_fails_closed(host, monkeypatch):
    unreal, project = host
    unreal.PluginBlueprintLibrary.get_plugin_descriptor_file_path = lambda name: None
    monkeypatch.setattr("dcc_mcp_core.elicitation.elicit_form_sync", lambda *a, **kw: pytest.fail("must not ask"))
    plan = plugin_configuration_plan(unreal, "speedtree_import")
    assert (
        apply_plugin_configuration(unreal, "speedtree_import", plan["project_sha256"])["status"]
        == "plugin_not_installed"
    )
    assert json.loads(project.read_text())["Plugins"] == []


def test_configuration_tool_cannot_accept_model_confirmation():
    import yaml

    root = Path(__file__).parents[1]
    manifest = yaml.safe_load((root / "src/dcc_mcp_unreal/skills/unreal-automation/tools.yaml").read_text())
    tool = next(t for t in manifest["tools"] if t["name"] == "configure_plugins")
    assert set(tool["input_schema"]["properties"]) == {"capability", "mode", "expected_sha256"}
    assert tool["destructive"] is True
