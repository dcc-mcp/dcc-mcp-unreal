"""Export a Content Browser asset to a file on disk."""

from __future__ import annotations

import os

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def export_asset(
    asset_path: str = "",
    export_path: str = "",
    **kwargs,
) -> dict:
    """Export a Content Browser asset to disk.

    The export format is inferred from the ``export_path`` file extension:

    - ``.fbx`` — static mesh, skeletal mesh, or animation
    - ``.png`` / ``.tga`` / ``.bmp`` — texture
    - ``.wav`` — sound wave
    - ``.csv`` — data table
    - ``.obj`` — static mesh (OBJ format)

    Args:
        asset_path: Content Browser object path of the asset to export
            (e.g. ``"/Game/Meshes/SM_Cube.SM_Cube"``).
        export_path: Absolute destination file path on disk
            (e.g. ``"C:/exports/SM_Cube.fbx"``).

    Returns:
        dict: ActionResultModel with the exported file path.
    """
    import unreal  # noqa: PLC0415

    # --- validation ---
    if not asset_path:
        return skill_error(
            "Missing required parameter: 'asset_path'",
            "asset_path must be a Content Browser object path",
            possible_solutions=[
                "Use list_assets to find the correct object path",
                "Example: '/Game/Meshes/SM_Cube.SM_Cube'",
            ],
        )
    if not export_path:
        return skill_error(
            "Missing required parameter: 'export_path'",
            "export_path must be an absolute file path with a supported extension",
            possible_solutions=["Example: 'C:/exports/SM_Cube.fbx'"],
        )

    # Ensure output directory exists
    export_dir = os.path.dirname(export_path)
    if export_dir and not os.path.isdir(export_dir):
        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as exc:
            return skill_error(
                f"Cannot create export directory: {export_dir}",
                str(exc),
                possible_solutions=["Check write permissions for the export directory"],
            )

    # Load the asset
    asset = unreal.load_asset(asset_path)
    if asset is None:
        return skill_error(
            f"Asset not found: {asset_path}",
            f"unreal.load_asset returned None for '{asset_path}'",
            prompt="Use list_assets to find the correct asset path.",
            possible_solutions=[
                "Verify the asset path using list_assets",
                "Ensure the asset is not redirected or deleted",
            ],
        )

    # Build export task
    task = unreal.AssetExportTask()
    task.set_editor_property("object", asset)
    task.set_editor_property("filename", export_path)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_identical", True)
    task.set_editor_property("selected", False)
    task.set_editor_property("prompt", False)

    result = unreal.Exporter.run_asset_export_task(task)
    if not result:
        return skill_error(
            f"Export failed for '{asset_path}'",
            "Exporter.run_asset_export_task returned False",
            prompt="Check the Unreal Output Log for detailed export errors.",
            possible_solutions=[
                "Ensure the file extension matches the asset type",
                "Check write permissions for the export directory",
                "Try exporting manually via right-click → Asset Actions → Export",
            ],
        )

    file_size = os.path.getsize(export_path) if os.path.isfile(export_path) else 0

    return skill_success(
        f"Exported '{os.path.basename(export_path)}' ({file_size} bytes)",
        prompt=f"The exported file is at '{export_path}'.",
        asset_path=asset_path,
        export_path=export_path,
        file_size_bytes=file_size,
    )


def main(**kwargs) -> dict:
    return export_asset(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
