"""Import a file (FBX, PNG, WAV, …) into the Unreal Engine Content Browser."""

from __future__ import annotations

import os

from _asset_import import configure_fbx_options, primary_object_path
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


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
    **kwargs,
) -> dict:
    """Import a file from disk into the Content Browser.

    Supports any format Unreal's ``AssetTools`` can handle:
    FBX (static mesh / skeletal mesh / animation), PNG/TGA/JPEG (texture),
    WAV (sound), CSV (data table), and more.

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

    Returns:
        dict: ActionResultModel with the imported asset's object path.
    """
    import unreal  # noqa: PLC0415

    # --- validation ---
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

    # --- build import task ---
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", source_path)
    task.set_editor_property("destination_path", destination_path)
    task.set_editor_property("destination_name", asset_name)
    task.set_editor_property("replace_existing", replace_existing)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", True)
    if os.path.splitext(source_path)[1].lower() == ".fbx":
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
    return skill_success(
        f"Imported '{asset_name}' to {destination_path}",
        prompt=f"Use get_asset_info to inspect the imported asset at '{object_path}'.",
        asset_name=asset_name,
        object_path=object_path,
        destination_path=destination_path,
        source_path=source_path,
        imported_object_paths=imported_paths,
    )


def main(**kwargs) -> dict:
    return import_asset(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
