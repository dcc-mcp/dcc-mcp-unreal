"""Import a file (FBX, PNG, WAV, …) into the Unreal Engine Content Browser."""

from __future__ import annotations

import os

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def import_asset(
    source_path: str = "",
    destination_path: str = "/Game/Imports",
    asset_name: str = "",
    replace_existing: bool = False,
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

    object_path = imported[0]
    return skill_success(
        f"Imported '{asset_name}' to {destination_path}",
        prompt=f"Use get_asset_info to inspect the imported asset at '{object_path}'.",
        asset_name=asset_name,
        object_path=object_path,
        destination_path=destination_path,
        source_path=source_path,
    )


def main(**kwargs) -> dict:
    return import_asset(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
