from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-assets" / "scripts"


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EditorProperties:
    def __init__(self, **values) -> None:
        self.values = values

    def set_editor_property(self, name, value) -> None:
        self.values[name] = value

    def get_editor_property(self, name):
        return self.values[name]


def test_versioned_static_groom_name_is_append_only() -> None:
    module = _load_script("_groom_import", SCRIPTS / "_groom_import.py")
    existing = {"/Game/Grooms/G_Hair", "/Game/Grooms/G_Hair_v001"}
    editor_assets = types.SimpleNamespace(does_asset_exist=lambda path: path in existing)

    assert module.versioned_groom_name(editor_assets, "/Game/Grooms", "G_Hair") == "G_Hair_v002"


def test_import_static_groom_uses_explicit_factory_options_and_safe_version(tmp_path: Path) -> None:
    helper = _load_script("_groom_import", SCRIPTS / "_groom_import.py")

    class AssetImportTask(EditorProperties):
        pass

    class GroomImportOptions(EditorProperties):
        def __init__(self):
            super().__init__(conversion_settings=EditorProperties())

    class GroomAsset:
        def get_path_name(self):
            return "/Game/Grooms/G_Hair_v001.G_Hair_v001"

        def get_class(self):
            return types.SimpleNamespace(get_name=lambda: "GroomAsset")

        def get_editor_property(self, name):
            assert name == "hair_groups_info"
            return [
                EditorProperties(
                    num_curves=20_640,
                    num_guides=128,
                    num_curve_vertices=660_480,
                    num_guide_vertices=4_096,
                )
            ]

    groom = GroomAsset()
    task_holder = {}

    def import_asset_tasks(tasks):
        task_holder["task"] = tasks[0]
        tasks[0].get_objects = lambda: [groom]

    editor_assets = types.SimpleNamespace(
        does_asset_exist=lambda path: path == "/Game/Grooms/G_Hair",
    )
    unreal = types.ModuleType("unreal")
    unreal.AssetImportTask = AssetImportTask
    unreal.GroomAsset = GroomAsset
    unreal.HairStrandsFactory = type("HairStrandsFactory", (), {})
    unreal.GroomImportOptions = GroomImportOptions
    unreal.Vector = lambda x, y, z: (x, y, z)
    unreal.EditorAssetLibrary = editor_assets
    unreal.AssetToolsHelpers = types.SimpleNamespace(
        get_asset_tools=lambda: types.SimpleNamespace(import_asset_tasks=import_asset_tasks)
    )

    source = tmp_path / "hair.abc"
    source.write_bytes(b"abc")
    with patch.dict(sys.modules, {"_groom_import": helper, "unreal": unreal}):
        module = _load_script("import_static_groom", SCRIPTS / "import_static_groom.py")
        result = module.import_static_groom(
            source_path=str(source),
            destination_path="/Game/Grooms",
            asset_name="G_Hair",
            rotation=[0.0, 90.0, 0.0],
            scale=[1.0, 1.0, 1.0],
        )

    task = task_holder["task"]
    conversion = task.values["options"].values["conversion_settings"]
    assert result["success"] is True
    assert result["context"] == {
        "object_path": "/Game/Grooms/G_Hair_v001.G_Hair_v001",
        "asset_class": "GroomAsset",
        "requested_asset_name": "G_Hair",
        "versioned_asset_name": "G_Hair_v001",
        "destination_path": "/Game/Grooms",
        "source_path": str(source),
        "replace_existing": False,
        "group_count": 1,
        "curve_count": 20_640,
        "guide_count": 128,
        "curve_vertex_count": 660_480,
        "guide_vertex_count": 4_096,
    }
    assert task.values["factory"].__class__.__name__ == "HairStrandsFactory"
    assert task.values["replace_existing"] is False
    assert task.values["replace_existing_settings"] is False
    assert task.values["destination_name"] == "G_Hair_v001"
    assert conversion.values == {
        "rotation": (0.0, 90.0, 0.0),
        "scale": (1.0, 1.0, 1.0),
    }


def test_import_static_groom_rejects_non_alembic_and_invalid_vectors(tmp_path: Path) -> None:
    helper = _load_script("_groom_import", SCRIPTS / "_groom_import.py")
    unreal = types.ModuleType("unreal")
    with patch.dict(sys.modules, {"_groom_import": helper, "unreal": unreal}):
        module = _load_script("reject_static_groom", SCRIPTS / "import_static_groom.py")
        source = tmp_path / "hair.fbx"
        source.write_bytes(b"fbx")
        alembic = source.with_suffix(".abc")
        alembic.write_bytes(b"abc")
        result = module.import_static_groom(source_path=str(source))
        invalid_vector = module.import_static_groom(source_path=str(alembic), rotation=[0.0, 90.0])

    assert result["success"] is False
    assert "Alembic (.abc)" in result["error"]
    assert invalid_vector["success"] is False
    assert "three numeric values" in invalid_vector["error"]


def test_static_groom_tool_schema_is_explicit_and_append_only() -> None:
    skill_root = SCRIPTS.parent
    tools = yaml.safe_load((skill_root / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    tool = next(entry for entry in tools if entry["name"] == "import_static_groom")

    assert tool["source_file"] == "scripts/import_static_groom.py"
    assert tool["read_only"] is False
    assert tool["destructive"] is False
    assert tool["idempotent"] is False
    assert tool["input_schema"]["required"] == ["source_path"]
    assert "replace_existing" not in tool["input_schema"]["properties"]
    assert tool["input_schema"]["properties"]["rotation"]["default"] == [0.0, 0.0, 0.0]
    assert tool["input_schema"]["properties"]["scale"]["default"] == [1.0, 1.0, 1.0]
    assert tool["next-tools"]["on-success"] == [
        "unreal_assets__get_asset_info",
        "unreal_assets__import_groom_cache",
    ]
