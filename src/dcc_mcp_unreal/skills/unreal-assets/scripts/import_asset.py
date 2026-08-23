"""Import a file (FBX, PNG, WAV, …) into the Unreal Engine Content Browser."""

from __future__ import annotations

import os

from _asset_import import configure_alembic_geometry_cache_options, configure_fbx_options, primary_object_path
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.plugin_preflight import require_plugins


@skill_entry
def import_asset(
    source_path: str = "",
    destination_path: str = "/Game/Imports",
    asset_name: str = "",
    replace_existing: bool = False,
    combine_meshes: bool = True,
    import_materials: bool = True,
    import_textures: bool = True,
    import_as_skeletal: bool = False,
    import_animations: bool = True,
    import_as_geometry_cache: bool = False,
    source_color_space: str = "",
    non_color_texture: bool = False,
    **kwargs,
) -> dict:
    """Import a file from disk into the Content Browser.

    Supports any format Unreal's ``AssetTools`` can handle:
    FBX (static mesh / skeletal mesh / animation), Alembic (static mesh /
    Geometry Cache), PNG/TGA/JPEG (texture), WAV (sound), CSV (data table),
    and more.

    Args:
        source_path: Absolute path to the source file on disk
            (e.g. ``"C:/art/cube.fbx"``).
        destination_path: Content Browser destination folder
            (e.g. ``"/Game/Meshes"``).
        asset_name: Name for the imported asset. Defaults to the source
            file's stem if empty.
        replace_existing: If ``True``, overwrite an existing asset with the
            same name.
        combine_meshes: For FBX files, combine scene nodes into one static mesh.
        import_materials: For FBX files, import referenced materials.
        import_textures: For FBX files, import referenced textures.
        import_as_skeletal: For FBX files, import a skeletal mesh instead of a
            static mesh.
        import_animations: For skeletal FBX files, also import embedded animation.
        import_as_geometry_cache: For Alembic files, import an animated
            Geometry Cache instead of the default Static Mesh.
        source_color_space: Optional source gamut for color textures. Use
            ``"srgb"`` to convert sRGB/Rec.709 primaries into the project
            working color space while retaining Unreal's normal sRGB decode.
        non_color_texture: Disable sRGB decoding and source-gamut conversion
            for data textures such as Normal, Roughness, Metallic, and AO.

    Returns:
        dict: ActionResultModel with the imported asset's object path.
    """
    import unreal  # noqa: PLC0415

    # --- validation ---
    if source_color_space not in {"", "srgb"}:
        return skill_error(
            f"Unsupported source color space: {source_color_space}",
            "source_color_space must be empty or 'srgb'",
        )
    if source_color_space and non_color_texture:
        return skill_error(
            "Conflicting texture color settings",
            "source_color_space and non_color_texture cannot be used together",
        )

    if not source_path:
        return skill_error(
            "Missing required parameter: 'source_path'",
            "source_path must be an absolute path to an existing file",
            possible_solutions=["Provide the full path to the file you want to import"],
        )

    if not os.path.isfile(source_path):
        return skill_error(
            f"Source file not found: {source_path}",
            f"os.path.isfile returned False for '{source_path}'",
            possible_solutions=[
                "Check that the file path is correct and the file exists",
                "Use forward slashes or raw strings on Windows",
            ],
        )

    destination_path = destination_path.rstrip("/") or "/Game/Imports"
    if not asset_name:
        asset_name = os.path.splitext(os.path.basename(source_path))[0]

    extension = os.path.splitext(source_path)[1].lower()
    if import_as_geometry_cache and extension != ".abc":
        return skill_error(
            "Invalid Geometry Cache source",
            "import_as_geometry_cache requires an Alembic (.abc) source file",
        )
    if extension in {".usd", ".usda", ".usdc", ".usdz"}:
        preflight_error = require_plugins(unreal, "usd_import")
        if preflight_error is not None:
            return preflight_error

    # --- build import task ---
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", source_path)
    task.set_editor_property("destination_path", destination_path)
    task.set_editor_property("destination_name", asset_name)
    task.set_editor_property("replace_existing", replace_existing)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", True)
    if extension == ".fbx":
        task.set_editor_property(
            "options",
            configure_fbx_options(
                unreal,
                combine_meshes=combine_meshes,
                import_materials=import_materials,
                import_textures=import_textures,
                import_as_skeletal=import_as_skeletal,
                import_animations=import_animations,
            ),
        )
    elif extension == ".abc" and import_as_geometry_cache:
        task.set_editor_property("factory", unreal.AlembicImportFactory())
        task.set_editor_property("options", configure_alembic_geometry_cache_options(unreal))

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    asset_tools.import_asset_tasks([task])

    imported = task.get_editor_property("imported_object_paths")
    if not imported:
        return skill_error(
            f"Import failed for '{os.path.basename(source_path)}'",
            "AssetImportTask returned no imported objects — check the Output Log for details",
            prompt="Open the Unreal Output Log for detailed import error messages.",
            possible_solutions=[
                "Verify the file format is supported by Unreal Engine",
                "Check that the destination path exists or let Unreal create it",
                "Try importing the file manually via the Content Browser to see errors",
            ],
        )

    imported_paths = [str(path) for path in imported]
    object_path = primary_object_path(
        imported_paths,
        asset_name,
        import_as_skeletal=import_as_skeletal,
    )
    if source_color_space or non_color_texture:
        asset = unreal.EditorAssetLibrary.load_asset(object_path)
        if asset is None or not isinstance(asset, unreal.Texture):
            return skill_error(
                "Source color space is only supported for texture imports",
                f"Imported object is not a Texture: {object_path}",
            )
        settings = asset.get_editor_property("source_color_settings")
        settings.set_editor_property(
            "color_space",
            unreal.TextureColorSpace.TCS_NONE if non_color_texture else unreal.TextureColorSpace.TCS_S_RGB,
        )
        asset.set_editor_property("source_color_settings", settings)
        asset.set_editor_property("srgb", not non_color_texture)
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            return skill_error(
                f"Failed to save texture color settings: {object_path}",
                "EditorAssetLibrary.save_loaded_asset returned False",
            )

    return skill_success(
        f"Imported '{asset_name}' to {destination_path}",
        prompt=f"Use get_asset_info to inspect the imported asset at '{object_path}'.",
        asset_name=asset_name,
        object_path=object_path,
        destination_path=destination_path,
        source_path=source_path,
        imported_object_paths=imported_paths,
        source_color_space=source_color_space or None,
        non_color_texture=non_color_texture,
    )
