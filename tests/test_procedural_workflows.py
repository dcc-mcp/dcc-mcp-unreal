import importlib.util
from types import SimpleNamespace

import pytest

from dcc_mcp_unreal.procedural_workflows import ProceduralWorkflowError, inspect_capabilities, validate_request


def _host():
    class System:
        @staticmethod
        def get_engine_version():
            return "5.8.1"

    class Plugins:
        @staticmethod
        def get_enabled_plugin_names():
            return [
                "PCG",
                "ProceduralVegetationEditor",
                "MeshTerrainMode",
                "MeshPartition",
                "NaniteAssemblyEditorUtils",
            ]

    return SimpleNamespace(
        SystemLibrary=System,
        PluginBlueprintLibrary=Plugins,
        PCGGraph=type("PCGGraph", (), {}),
        ProceduralVegetation=type("ProceduralVegetation", (), {}),
        ProceduralVegetationGraph=type("ProceduralVegetationGraph", (), {}),
        NaniteAssemblyStaticMeshBuilder=type("NaniteAssemblyStaticMeshBuilder", (), {}),
        MeshPartitionDefinition=type("MeshPartitionDefinition", (), {}),
        MaterialExpressionSubstrateSlabBSDF=type("MaterialExpressionSubstrateSlabBSDF", (), {}),
    )


def test_capability_probe_is_read_only_and_reports_host_evidence():
    result = inspect_capabilities(_host())
    assert result["observation"].startswith("read_only")
    assert result["capabilities"]["nanite_foliage"]["status"] == "available"
    assert result["capabilities"]["substrate"]["status"] == "available"
    assert result["capabilities"]["megalights"]["status"] == "available"


def test_manual_override_requires_project_owned_dcc_cua_binding():
    request = {"owned_window": {"provider": "dcc-cua", "runtime_version": "0.4.0", "target_pid": 42, "hwnd": 99}, "expected_revision": "abc"}
    result = validate_request("pcg_manual_overrides", "exclude", request)
    assert result["plan"]["routing"] == "dcc-cua"
    with pytest.raises(ProceduralWorkflowError, match="dcc-cua"):
        validate_request("pcg_manual_overrides", "exclude", {**request, "owned_window": {**request["owned_window"], "provider": "generic"}})


def test_pve_rejects_cross_version_implicit_migration():
    with pytest.raises(ProceduralWorkflowError, match="implicitly migrated"):
        validate_request(
            "procedural_vegetation",
            "export",
            {"engine_version": "5.8", "source_engine_version": "5.7", "destination_path": "/Game/Vegetation/Tree"},
        )


def test_nanite_foliage_distinguishes_ordinary_nanite():
    with pytest.raises(ProceduralWorkflowError, match="ordinary Nanite"):
        validate_request(
            "nanite_foliage",
            "configure",
            {"ordinary_nanite": True, "workflow": "assembly", "asset_path": "/Game/Foliage/Tree", "target_rhi": "dx12"},
        )


def test_mesh_terrain_rejects_unsafe_pcg_write_and_preview_is_explicit():
    with pytest.raises(ProceduralWorkflowError, match="correspondence"):
        validate_request(
            "mesh_terrain",
            "edit",
            {"world_partition": True, "source_type": "heightmap", "pcg_write": True, "source_point_correspondence": False},
        )
    result = validate_request("mesh_terrain", "build", {"world_partition": True, "source_type": "mesh", "build_state": "preview"})
    assert result["plan"]["preview_only"] is True


def test_megalights_requires_a_declared_target_budget_and_deferred_renderer():
    result = validate_request(
        "megalights",
        "qualify",
        {"engine_version": "5.8", "renderer": "deferred", "target_rhi": "dx12", "target_budget": {"gpu_ms": 16.6, "memory_mb": 2048}},
    )
    assert result["plan"]["qualification_requires_measurement"] is True


def test_substrate_conversion_requires_explicit_recovery_contract():
    with pytest.raises(ProceduralWorkflowError, match="disposable_copy"):
        validate_request("substrate", "convert", {"material_path": "/Game/Materials/M_My", "root": "slab", "conversion_intent": True})
    result = validate_request(
        "substrate",
        "convert",
        {"material_path": "/Game/Materials/M_My", "root": "slab", "conversion_intent": True, "disposable_copy": True, "backup_required": True},
    )
    assert result["plan"]["legacy_preserved"] is False


def test_validation_skill_uses_normal_skill_error_without_unreal():
    path = "src/dcc_mcp_unreal/skills/unreal-procedural/scripts/validate_procedural_workflow.py"
    spec = importlib.util.spec_from_file_location("validate_procedural_workflow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.validate_procedural_workflow(
        feature="megalights",
        operation="qualify",
        request={"engine_version": "5.8", "renderer": "forward", "target_rhi": "dx12", "target_budget": {"gpu_ms": 1, "memory_mb": 1}},
    )
    assert result["success"] is False
    assert result["context"]["error_kind"] == "invalid_input"

