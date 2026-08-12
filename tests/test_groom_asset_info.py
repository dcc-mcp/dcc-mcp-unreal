from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1]
    / "src"
    / "dcc_mcp_unreal"
    / "skills"
    / "unreal-assets"
    / "scripts"
    / "get_asset_info.py"
)


def _load_module(monkeypatch):
    core_skill = types.ModuleType("dcc_mcp_core.skill")
    core_skill.skill_entry = lambda function: function
    core_skill.skill_error = lambda *args, **kwargs: {"success": False, **kwargs}
    core_skill.skill_success = lambda message, **kwargs: {"success": True, "message": message, **kwargs}
    monkeypatch.setitem(sys.modules, "dcc_mcp_core.skill", core_skill)

    asset_data = types.ModuleType("_asset_data")
    asset_data.configure_dependency_options = lambda options: options
    asset_data.object_path = lambda data: str(data.object_path)
    monkeypatch.setitem(sys.modules, "_asset_data", asset_data)

    spec = importlib.util.spec_from_file_location("_test_get_asset_info", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EditorProperties:
    def __init__(self, **values):
        self.values = values

    def get_editor_property(self, name):
        if name not in self.values:
            raise RuntimeError("property unavailable")
        return self.values[name]


def test_extract_groom_asset_info_summarizes_all_hair_groups(monkeypatch):
    module = _load_module(monkeypatch)
    groom = EditorProperties(
        hair_groups_info=[
            EditorProperties(
                group_index=0,
                group_id=4,
                group_name="Crown",
                num_curves=900_000,
                num_guides=90_000,
                num_curve_vertices=12_000_000,
                num_guide_vertices=1_200_000,
                max_curve_length=0.72,
            ),
            EditorProperties(
                group_index=1,
                group_id=9,
                group_name="Fringe",
                num_curves=171_891,
                num_guides=17_189,
                num_curve_vertices=4_497_312,
                num_guide_vertices=449_091,
                max_curve_length=0.41,
            ),
        ]
    )

    info = module._extract_groom_asset_info(groom)

    assert info["groom_group_count"] == 2
    assert info["groom_total_curves"] == 1_071_891
    assert info["groom_total_guides"] == 107_189
    assert info["groom_total_curve_vertices"] == 16_497_312
    assert info["groom_total_guide_vertices"] == 1_649_091
    assert info["groom_groups"][0] == {
        "group_index": 0,
        "group_id": 4,
        "group_name": "Crown",
        "num_curves": 900_000,
        "num_guides": 90_000,
        "num_curve_vertices": 12_000_000,
        "num_guide_vertices": 1_200_000,
        "max_curve_length": 0.72,
    }


def test_extract_groom_asset_info_degrades_when_property_is_unavailable(monkeypatch):
    module = _load_module(monkeypatch)

    assert module._extract_groom_asset_info(EditorProperties()) == {
        "groom_metadata_available": False,
        "groom_metadata_error": "hair_groups_info is unavailable",
    }
