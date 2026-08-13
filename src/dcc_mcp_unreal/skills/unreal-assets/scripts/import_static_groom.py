"""Safely import a static Alembic GroomAsset into Unreal."""

from __future__ import annotations

import os

from _groom_import import groom_topology, vector3, versioned_groom_name
from dcc_mcp_core.skill import skill_entry, skill_error, skill_exception, skill_success


@skill_entry
def import_static_groom(
    source_path: str = "",
    destination_path: str = "/Game/Grooms",
    asset_name: str = "",
    rotation=None,
    scale=None,
    **kwargs,
) -> dict:
    """Import a versioned GroomAsset without replacing an existing asset."""
    import unreal  # noqa: PLC0415

    if not source_path or not os.path.isfile(source_path):
        return skill_error(
            "Static Groom source not found",
            "source_path must be an absolute path to an existing Alembic (.abc) file",
        )
    if os.path.splitext(source_path)[1].lower() != ".abc":
        return skill_error("Invalid static Groom source", "Static Groom import requires an Alembic (.abc) file")
    try:
        rotation_xyz = vector3([0.0, 0.0, 0.0] if rotation is None else rotation, "rotation")
        scale_xyz = vector3([1.0, 1.0, 1.0] if scale is None else scale, "scale")
    except ValueError as exc:
        return skill_error("Invalid static Groom conversion", str(exc))
    if any(component == 0.0 for component in scale_xyz):
        return skill_error("Invalid static Groom conversion", "scale components must be non-zero")

    destination_path = destination_path.rstrip("/") or "/Game/Grooms"
    requested_name = asset_name or os.path.splitext(os.path.basename(source_path))[0]
    editor_assets = unreal.EditorAssetLibrary
    try:
        versioned_name = versioned_groom_name(editor_assets, destination_path, requested_name)
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", source_path)
        task.set_editor_property("destination_path", destination_path)
        task.set_editor_property("destination_name", versioned_name)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        task.set_editor_property("replace_existing", False)
        task.set_editor_property("replace_existing_settings", False)
        task.set_editor_property("factory", unreal.HairStrandsFactory())

        options = unreal.GroomImportOptions()
        conversion = options.get_editor_property("conversion_settings")
        conversion.set_editor_property("rotation", unreal.Vector(*rotation_xyz))
        conversion.set_editor_property("scale", unreal.Vector(*scale_xyz))
        options.set_editor_property("conversion_settings", conversion)
        task.set_editor_property("options", options)

        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        grooms = [obj for obj in task.get_objects() if isinstance(obj, unreal.GroomAsset)]
        if not grooms:
            return skill_error(
                "Static Groom import produced no GroomAsset",
                "HairStrandsFactory returned no GroomAsset; verify the Alembic schema and HairStrands plugin",
                requested_asset_name=requested_name,
                versioned_asset_name=versioned_name,
            )
        groom = grooms[0]
        return skill_success(
            "Imported versioned static Groom '{}'".format(versioned_name),
            prompt="Use get_asset_info to verify the Groom topology before importing a Groom Cache.",
            object_path=groom.get_path_name(),
            asset_class=groom.get_class().get_name(),
            requested_asset_name=requested_name,
            versioned_asset_name=versioned_name,
            destination_path=destination_path,
            source_path=source_path,
            replace_existing=False,
            **groom_topology(groom),
        )
    except Exception as exc:
        return skill_exception(exc, message="Failed to import versioned static Groom")
