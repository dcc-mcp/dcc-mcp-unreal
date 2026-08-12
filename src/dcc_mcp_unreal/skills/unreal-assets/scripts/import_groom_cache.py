"""Safely import an Alembic Groom Cache against an existing GroomAsset."""

from __future__ import annotations

import os

from _groom_cache_import import object_path, versioned_groom_cache_name
from dcc_mcp_core.skill import skill_entry, skill_error, skill_exception, skill_success


@skill_entry
def import_groom_cache(
    source_path: str = "",
    groom_asset_path: str = "",
    destination_path: str = "/Game/GroomCaches",
    asset_name: str = "",
    frame_start: int = 0,
    frame_end: int = 0,
    import_type: str = "strands",
    **kwargs,
) -> dict:
    """Import a versioned Groom Cache without replacing a referenced cache.

    The source topology must match the existing GroomAsset. This tool cannot
    prove Alembic topology compatibility before Unreal imports the file, so it
    always creates a new versioned cache and never overwrites an existing one.
    """
    import unreal  # noqa: PLC0415

    if not source_path or not os.path.isfile(source_path):
        return skill_error(
            "Groom Cache source not found",
            "source_path must be an absolute path to an existing Alembic (.abc) file",
        )
    if os.path.splitext(source_path)[1].lower() != ".abc":
        return skill_error("Invalid Groom Cache source", "Groom Cache import requires an Alembic (.abc) file")
    if not groom_asset_path:
        return skill_error("Missing Groom asset", "groom_asset_path is required as the topology reference")
    if import_type not in {"strands", "guides"}:
        return skill_error("Invalid Groom Cache import type", "import_type must be 'strands' or 'guides'")
    if frame_start < 0 or frame_end < frame_start:
        return skill_error("Invalid Groom Cache frame range", "frame_start must be >= 0 and frame_end >= frame_start")

    destination_path = destination_path.rstrip("/") or "/Game/GroomCaches"
    requested_name = asset_name or os.path.splitext(os.path.basename(source_path))[0]
    editor_assets = unreal.EditorAssetLibrary
    groom_object_path = object_path(groom_asset_path)
    groom = editor_assets.load_asset(groom_asset_path) or editor_assets.load_asset(groom_object_path)
    if groom is None or not isinstance(groom, unreal.GroomAsset):
        return skill_error(
            "Groom asset not found",
            "groom_asset_path must resolve to an existing GroomAsset",
            groom_asset_path=groom_asset_path,
        )

    try:
        versioned_name = versioned_groom_cache_name(editor_assets, destination_path, requested_name)
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", source_path)
        task.set_editor_property("destination_path", destination_path)
        task.set_editor_property("destination_name", versioned_name)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        task.set_editor_property("replace_existing", False)
        task.set_editor_property("replace_existing_settings", False)
        task.set_editor_property("factory", unreal.HairStrandsFactory())

        options = unreal.GroomCacheImportOptions()
        settings = options.get_editor_property("import_settings")
        settings.set_editor_property("import_groom_cache", True)
        settings.set_editor_property("import_groom_asset", False)
        settings.set_editor_property(
            "import_type",
            unreal.GroomCacheImportType.STRANDS if import_type == "strands" else unreal.GroomCacheImportType.GUIDES,
        )
        settings.set_editor_property("frame_start", frame_start)
        settings.set_editor_property("frame_end", frame_end)
        settings.set_editor_property("groom_asset", unreal.SoftObjectPath(groom_object_path))
        settings.set_editor_property("override_conversion_settings", False)
        options.set_editor_property("import_settings", settings)
        task.set_editor_property("options", options)

        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        objects = list(task.get_objects())
        caches = [obj for obj in objects if isinstance(obj, unreal.GroomCache)]
        if not caches:
            return skill_error(
                "Groom Cache import produced no cache asset",
                "HairStrandsFactory returned no GroomCache; verify matching topology and the HairStrands plugin",
                requested_asset_name=requested_name,
                versioned_asset_name=versioned_name,
            )
        imported = caches[0]
        imported_path = imported.get_path_name()
        return skill_success(
            "Imported versioned Groom Cache '{}'".format(versioned_name),
            prompt="Bind this cache to a GroomComponent or Sequencer Groom Cache track.",
            object_path=imported_path,
            asset_class=imported.get_class().get_name(),
            requested_asset_name=requested_name,
            versioned_asset_name=versioned_name,
            groom_asset_path=groom_object_path,
            destination_path=destination_path,
            source_path=source_path,
            frame_start=frame_start,
            frame_end=frame_end,
            import_type=import_type,
            replace_existing=False,
        )
    except Exception as exc:
        return skill_exception(exc, message="Failed to import versioned Groom Cache")
