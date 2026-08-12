from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

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


def test_versioned_groom_cache_name_checks_factory_suffix() -> None:
    module = _load_script("_groom_cache_import", SCRIPTS / "_groom_cache_import.py")
    existing = {
        "/Game/Caches/GC_Hair",
        "/Game/Caches/GC_Hair_strands_cache",
        "/Game/Caches/GC_Hair_v001_strands_cache",
    }
    editor_assets = types.SimpleNamespace(does_asset_exist=lambda path: path in existing)

    assert module.versioned_groom_cache_name(editor_assets, "/Game/Caches", "GC_Hair") == "GC_Hair_v002"


def test_import_groom_cache_uses_safe_version_and_existing_groom(tmp_path: Path) -> None:
    helper = _load_script("_groom_cache_import", SCRIPTS / "_groom_cache_import.py")

    class AssetImportTask(EditorProperties):
        pass

    class GroomAsset:
        def get_path_name(self):
            return "/Game/Grooms/G_Hair.G_Hair"

    class GroomCache:
        def get_path_name(self):
            return "/Game/Caches/GC_Hair_v001_strands_cache.GC_Hair_v001_strands_cache"

        def get_class(self):
            return types.SimpleNamespace(get_name=lambda: "GroomCache")

    class GroomCacheImportOptions(EditorProperties):
        def __init__(self):
            super().__init__(import_settings=EditorProperties())

    groom = GroomAsset()
    cache = GroomCache()
    task_holder = {}

    def import_asset_tasks(tasks):
        task_holder["task"] = tasks[0]
        tasks[0].get_objects = lambda: [cache]

    existing = {"/Game/Caches/GC_Hair_strands_cache"}
    editor_assets = types.SimpleNamespace(
        does_asset_exist=lambda path: path in existing,
        load_asset=lambda path: groom if path == "/Game/Grooms/G_Hair" else None,
    )
    unreal = types.ModuleType("unreal")
    unreal.AssetImportTask = AssetImportTask
    unreal.GroomAsset = GroomAsset
    unreal.GroomCache = GroomCache
    unreal.HairStrandsFactory = type("HairStrandsFactory", (), {})
    unreal.GroomCacheImportOptions = GroomCacheImportOptions
    unreal.GroomCacheImportType = types.SimpleNamespace(STRANDS="strands", GUIDES="guides")
    unreal.SoftObjectPath = lambda value: ("soft", value)
    unreal.EditorAssetLibrary = editor_assets
    unreal.AssetToolsHelpers = types.SimpleNamespace(
        get_asset_tools=lambda: types.SimpleNamespace(import_asset_tasks=import_asset_tasks)
    )

    source = tmp_path / "hair_cache.abc"
    source.write_bytes(b"abc")
    with patch.dict(sys.modules, {"_groom_cache_import": helper, "unreal": unreal}):
        module = _load_script("import_groom_cache", SCRIPTS / "import_groom_cache.py")
        result = module.import_groom_cache(
            source_path=str(source),
            groom_asset_path="/Game/Grooms/G_Hair",
            destination_path="/Game/Caches",
            asset_name="GC_Hair",
            frame_start=0,
            frame_end=1,
        )

    task = task_holder["task"]
    settings = task.values["options"].values["import_settings"]
    assert result["success"] is True
    context = result["context"]
    assert context["requested_asset_name"] == "GC_Hair"
    assert context["versioned_asset_name"] == "GC_Hair_v001"
    assert context["object_path"].endswith("GC_Hair_v001_strands_cache.GC_Hair_v001_strands_cache")
    assert task.values["replace_existing"] is False
    assert task.values["replace_existing_settings"] is False
    assert task.values["destination_name"] == "GC_Hair_v001"
    assert settings.values == {
        "import_groom_cache": True,
        "import_groom_asset": False,
        "import_type": "strands",
        "frame_start": 0,
        "frame_end": 1,
        "groom_asset": ("soft", "/Game/Grooms/G_Hair.G_Hair"),
        "override_conversion_settings": False,
    }


def test_import_groom_cache_rejects_non_alembic_source(tmp_path: Path) -> None:
    helper = _load_script("_groom_cache_import", SCRIPTS / "_groom_cache_import.py")
    source = tmp_path / "hair_cache.fbx"
    source.write_bytes(b"fbx")
    unreal = types.ModuleType("unreal")

    with patch.dict(sys.modules, {"_groom_cache_import": helper, "unreal": unreal}):
        module = _load_script("reject_groom_cache", SCRIPTS / "import_groom_cache.py")
        result = module.import_groom_cache(
            source_path=str(source),
            groom_asset_path="/Game/Grooms/G_Hair",
        )

    assert result["success"] is False
    assert "Alembic (.abc)" in result["error"]
