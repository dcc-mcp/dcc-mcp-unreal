"""Behavioral contracts for Alembic Geometry Cache import and materials."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
ASSET_SCRIPTS = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-assets" / "scripts"
MATERIAL_SKILL = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-materials"


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alembic_import_explicitly_selects_geometry_cache(tmp_path: Path) -> None:
    helper = _load_script("_asset_import", ASSET_SCRIPTS / "_asset_import.py")

    class EditorProperties:
        def __init__(self) -> None:
            self.values = {}

        def set_editor_property(self, name, value) -> None:
            self.values[name] = value

        def get_editor_property(self, name):
            return self.values[name]

    class AssetImportTask(EditorProperties):
        pass

    class AbcImportSettings(EditorProperties):
        pass

    class AlembicImportFactory:
        pass

    task_holder = {}

    def import_asset_tasks(tasks) -> None:
        task_holder["task"] = tasks[0]
        tasks[0].values["imported_object_paths"] = ["/Game/Horses/GC_Horse.GC_Horse"]

    asset_tools = types.SimpleNamespace(import_asset_tasks=import_asset_tasks)
    unreal = types.ModuleType("unreal")
    unreal.AssetImportTask = AssetImportTask
    unreal.AbcImportSettings = AbcImportSettings
    unreal.AlembicImportFactory = AlembicImportFactory
    unreal.AlembicImportType = types.SimpleNamespace(GEOMETRY_CACHE="geometry_cache")
    unreal.AssetToolsHelpers = types.SimpleNamespace(get_asset_tools=lambda: asset_tools)

    source = tmp_path / "horse.abc"
    source.write_bytes(b"abc")
    with patch.dict(sys.modules, {"_asset_import": helper, "unreal": unreal}):
        module = _load_script("import_geometry_cache", ASSET_SCRIPTS / "import_asset.py")
        result = module.import_asset(
            source_path=str(source),
            destination_path="/Game/Horses",
            asset_name="GC_Horse",
            import_as_geometry_cache=True,
        )

    task = task_holder["task"]
    assert result["success"] is True
    assert isinstance(task.values["factory"], AlembicImportFactory)
    assert task.values["options"].values["import_type"] == "geometry_cache"


def test_geometry_cache_import_rejects_non_alembic_source(tmp_path: Path) -> None:
    helper = _load_script("_asset_import", ASSET_SCRIPTS / "_asset_import.py")
    unreal = types.ModuleType("unreal")
    unreal.AssetImportTask = MagicMock
    source = tmp_path / "horse.fbx"
    source.write_bytes(b"fbx")

    with patch.dict(sys.modules, {"_asset_import": helper, "unreal": unreal}):
        module = _load_script("reject_non_alembic_cache", ASSET_SCRIPTS / "import_asset.py")
        result = module.import_asset(
            source_path=str(source),
            destination_path="/Game/Horses",
            import_as_geometry_cache=True,
        )

    assert result["success"] is False
    assert "requires an Alembic (.abc)" in result["error"]


def test_texture_import_can_declare_srgb_source_gamut(tmp_path: Path) -> None:
    helper = _load_script("_asset_import", ASSET_SCRIPTS / "_asset_import.py")

    class EditorProperties:
        def __init__(self, **values) -> None:
            self.values = values

        def set_editor_property(self, name, value) -> None:
            self.values[name] = value

        def get_editor_property(self, name):
            return self.values[name]

    class AssetImportTask(EditorProperties):
        pass

    class Texture(EditorProperties):
        pass

    texture = Texture(source_color_settings=EditorProperties(color_space="none"), srgb=False)
    editor_assets = MagicMock()
    editor_assets.load_asset.return_value = texture
    editor_assets.save_loaded_asset.return_value = True

    def import_asset_tasks(tasks) -> None:
        tasks[0].values["imported_object_paths"] = ["/Game/Chart/T_Chart.T_Chart"]

    unreal = types.ModuleType("unreal")
    unreal.AssetImportTask = AssetImportTask
    unreal.Texture = Texture
    unreal.TextureColorSpace = types.SimpleNamespace(TCS_NONE="none", TCS_S_RGB="srgb")
    unreal.AssetToolsHelpers = types.SimpleNamespace(
        get_asset_tools=lambda: types.SimpleNamespace(import_asset_tasks=import_asset_tasks)
    )
    unreal.EditorAssetLibrary = editor_assets

    source = tmp_path / "chart.png"
    source.write_bytes(b"png")
    with patch.dict(sys.modules, {"_asset_import": helper, "unreal": unreal}):
        module = _load_script("import_srgb_texture", ASSET_SCRIPTS / "import_asset.py")
        result = module.import_asset(
            source_path=str(source),
            destination_path="/Game/Chart",
            asset_name="T_Chart",
            source_color_space="srgb",
        )
        color_space_after_srgb = texture.values["source_color_settings"].values["color_space"]
        srgb_after_srgb = texture.values["srgb"]
        non_color_result = module.import_asset(
            source_path=str(source),
            destination_path="/Game/Chart",
            asset_name="T_Chart",
            non_color_texture=True,
        )

    assert result["success"] is True
    assert non_color_result["success"] is True
    assert color_space_after_srgb == "srgb"
    assert srgb_after_srgb is True
    assert texture.values["source_color_settings"].values["color_space"] == "none"
    assert texture.values["srgb"] is False
    assert editor_assets.save_loaded_asset.call_count == 2


def test_geometry_cache_material_assignment_updates_and_saves_asset() -> None:
    class MaterialInterface:
        pass

    class StaticMesh:
        pass

    class GeometryCache:
        def __init__(self) -> None:
            self.materials = []

        def get_editor_property(self, name):
            assert name == "materials"
            return self.materials

        def set_editor_property(self, name, value) -> None:
            assert name == "materials"
            self.materials = value

    material = MaterialInterface()
    cache = GeometryCache()
    editor_assets = MagicMock()
    editor_assets.load_asset.side_effect = lambda path: {
        "/Game/Horses/GC_Horse": cache,
        "/Game/Horses/M_Horse": material,
    }.get(path)
    editor_assets.save_loaded_asset.return_value = True

    unreal = types.ModuleType("unreal")
    unreal.MaterialInterface = MaterialInterface
    unreal.StaticMesh = StaticMesh
    unreal.GeometryCache = GeometryCache
    unreal.EditorAssetLibrary = editor_assets

    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "assign_geometry_cache_material",
            MATERIAL_SKILL / "scripts" / "assign_material.py",
        )
        result = module.assign_material(
            target_kind="geometry_cache",
            target_path="/Game/Horses/GC_Horse",
            material_path="/Game/Horses/M_Horse",
            slot_index=0,
        )

    assert result["success"] is True
    assert cache.materials == [material]
    editor_assets.save_loaded_asset.assert_called_once_with(cache, only_if_is_dirty=False)


def test_material_assignment_accepts_ue_material_class_not_python_interface_subclass() -> None:
    class Material:
        def get_class(self):
            return type("Class", (), {"get_name": lambda _self: "Material"})()

    class StaticMesh:
        def set_material(self, slot, value) -> None:
            self.material = (slot, value)

    material = Material()
    mesh = StaticMesh()
    editor_assets = MagicMock()
    editor_assets.load_asset.side_effect = lambda path: mesh if path.endswith("SM_Road_Straight") else material
    editor_assets.save_loaded_asset.return_value = True

    unreal = types.ModuleType("unreal")
    unreal.MaterialInterface = type("MaterialInterface", (), {})
    unreal.StaticMesh = StaticMesh
    unreal.GeometryCache = type("GeometryCache", (), {})
    unreal.EditorAssetLibrary = editor_assets

    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "assign_native_material",
            MATERIAL_SKILL / "scripts" / "assign_material.py",
        )
        result = module.assign_material(
            target_kind="static_mesh",
            target_path="/Game/City/Roads/SM_Road_Straight",
            material_path="/Game/City/Materials/M_Road012A_PBR",
            slot_index=1,
        )

    assert result["success"] is True
    assert mesh.material == (1, material)


def test_geometry_cache_parameters_are_declared_in_tool_schemas() -> None:
    asset_tools = yaml.safe_load((ASSET_SCRIPTS.parent / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    import_schema = next(tool for tool in asset_tools if tool["name"] == "import_asset")["input_schema"]
    assert import_schema["properties"]["import_as_geometry_cache"] == {
        "type": "boolean",
        "description": "For Alembic files, import an animated Geometry Cache instead of a Static Mesh.",
        "default": False,
    }
    assert import_schema["properties"]["source_color_space"]["enum"] == ["", "srgb"]
    assert import_schema["properties"]["non_color_texture"]["default"] is False

    material_tools = yaml.safe_load((MATERIAL_SKILL / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    assign_schema = next(tool for tool in material_tools if tool["name"] == "assign_material")["input_schema"]
    assert "geometry_cache" in assign_schema["properties"]["target_kind"]["enum"]
