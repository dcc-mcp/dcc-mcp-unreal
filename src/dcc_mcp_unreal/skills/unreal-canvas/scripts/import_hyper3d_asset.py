"""Import a downloaded Hyper3D model into Unreal's Content Browser."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

SUPPORTED_EXTENSIONS = {".glb", ".fbx", ".obj", ".usdz", ".stl"}


@skill_entry
def import_hyper3d_asset(
    source_path: str = "",
    destination_path: str = "/Game/Merlin/Generated",
    asset_name: str = "",
    replace_existing: bool = False,
    **kwargs,
) -> dict:
    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return skill_error(
            "Unreal Engine is not available",
            "unreal_module_missing",
            possible_solutions=["Run this skill through the Unreal DCC-MCP adapter."],
        )

    source = Path(source_path).expanduser()
    if not source.is_absolute() or not source.is_file():
        return skill_error(
            "Hyper3D source file was not found",
            "invalid_source_path",
            possible_solutions=["Provide the absolute path returned by download_hyper3d_result."],
        )
    if source.suffix.casefold() not in SUPPORTED_EXTENSIONS:
        return skill_error(
            "Unsupported Hyper3D model format",
            "unsupported_source_format",
            possible_solutions=["Download a GLB or FBX result for the broadest Unreal compatibility."],
        )
    if not destination_path.startswith("/Game/") or destination_path.endswith("/"):
        return skill_error("Invalid Content Browser destination", "invalid_destination_path")

    name = asset_name.strip() or source.stem
    if not name or Path(name).name != name or name in {".", ".."}:
        return skill_error("Unable to determine an Unreal asset name", "invalid_asset_name")

    try:
        with tempfile.TemporaryDirectory(prefix="dcc_mcp_hyper3d_") as staging_dir:
            staged_source = Path(staging_dir) / f"{name}{source.suffix}"
            shutil.copy2(source, staged_source)
            task = unreal.AssetImportTask()
            task.set_editor_property("filename", str(staged_source))
            task.set_editor_property("destination_path", destination_path)
            task.set_editor_property("destination_name", name)
            task.set_editor_property("replace_existing", bool(replace_existing))
            task.set_editor_property("automated", True)
            task.set_editor_property("save", True)
            unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
            imported = task.get_editor_property("imported_object_paths")
    except Exception as exc:
        return skill_error("Failed to import the Hyper3D asset", type(exc).__name__)

    imported_paths = [str(path) for path in (imported or [])]
    if not imported_paths:
        return skill_error(
            "Unreal did not import the Hyper3D asset",
            "empty_import_result",
            possible_solutions=[
                "Enable the Interchange and relevant format import plugins.",
                "Try importing the downloaded file manually to inspect the Unreal Output Log.",
            ],
        )
    return skill_success(
        f"Imported Hyper3D asset '{name}' into {destination_path}.",
        prompt="Inspect the imported object paths or place the asset in the level with an Unreal actor tool.",
        source_path=str(source),
        destination_path=destination_path,
        asset_name=name,
        imported_object_paths=imported_paths,
    )
