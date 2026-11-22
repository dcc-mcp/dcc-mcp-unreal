import importlib.util
import sys
from types import SimpleNamespace


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_skill_requires_a_live_unreal_asset_registry(monkeypatch):
    script = _load(
        "plan_asset_handoff_skill",
        "src/dcc_mcp_unreal/skills/unreal-assets/scripts/plan_asset_handoff.py",
    )
    monkeypatch.setitem(sys.modules, "unreal", None)
    result = script.plan_asset_handoff(
        asset_paths=["/Plugin/Materials/MI_Mud"], source_root="/Plugin", destination_root="/Game/Localized"
    )
    assert result["success"] is False
    assert result["context"]["error_kind"] == "host_unavailable"


def test_plan_skill_uses_registry_dependencies_without_mutation(monkeypatch):
    script = _load(
        "plan_asset_handoff_skill_live",
        "src/dcc_mcp_unreal/skills/unreal-assets/scripts/plan_asset_handoff.py",
    )

    class Registry:
        def get_dependencies(self, package, _options):
            return {
                "/Plugin/Materials/MI_Mud": ["/Plugin/Textures/T_Mud", "/Script/Engine.Material"],
                "/Plugin/Textures/T_Mud": [],
            }[package]

    host = SimpleNamespace(
        AssetRegistryHelpers=SimpleNamespace(get_asset_registry=lambda: Registry()),
        AssetRegistryDependencyOptions=lambda: object(),
    )
    monkeypatch.setitem(sys.modules, "unreal", host)
    result = script.plan_asset_handoff(
        asset_paths=["/Plugin/Materials/MI_Mud"], source_root="/Plugin", destination_root="/Game/Localized"
    )
    assert result["success"] is True
    assert result["context"]["assets_mutated"] is False
    assert result["context"]["plan"]["copy"][0]["destination"] == "/Game/Localized/Materials/MI_Mud"
