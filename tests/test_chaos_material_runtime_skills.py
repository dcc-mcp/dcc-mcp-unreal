from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src" / "dcc_mcp_unreal" / "skills"


def test_core_fracture_editor_skills_are_typed_and_discoverable() -> None:
    expected = {
        "unreal-chaos": ["create_geometry_collection", "spawn_geometry_collection_actor"],
        "unreal-materials": ["create_material_instance", "set_material_instance_parameters", "assign_material"],
        "unreal-runtime": ["start_physics_simulation", "stop_physics_simulation"],
    }

    for skill, tools in expected.items():
        assert (SKILLS / skill / "SKILL.md").is_file()
        tool_text = (SKILLS / skill / "tools.yaml").read_text(encoding="utf-8")
        for tool in tools:
            assert f"name: {tool}" in tool_text
            script = SKILLS / skill / "scripts" / f"{tool}.py"
            assert "@skill_entry" in script.read_text(encoding="utf-8")


def test_chaos_conversion_splits_disconnected_mesh_islands_into_clustered_fragments() -> None:
    source = (
        ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpAutomationLibrary.cpp"
    ).read_text(encoding="utf-8")

    assert "FGeometryCollectionEngineConversion::AppendStaticMesh" in source
    assert "FGeometryCollectionClusteringUtility::ClusterAllBonesUnderNewRoot" in source
    assert "GeometryCollectionAlgo::PrepareForSimulation" in source
    assert "GeometryCollection->DamageThreshold = {DamageThreshold};" in source
