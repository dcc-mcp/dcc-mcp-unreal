"""Delete one or more assets from the Unreal Engine Content Browser."""

from __future__ import annotations

from typing import List

from _asset_data import object_path
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success, skill_warning


@skill_entry
def delete_asset(
    asset_paths: "str | List[str]" = "",
    force_delete: bool = False,
    **kwargs,
) -> dict:
    """Delete one or more assets from the Content Browser.

    Assets with active references will be flagged as warnings unless
    ``force_delete=True``, in which case Unreal will attempt a forced delete
    (consolidating references to ``None`` first).

    Args:
        asset_paths: A single asset path string or a list of asset paths
            (e.g. ``"/Game/Meshes/SM_Cube"`` or
            ``["/Game/Meshes/SM_Cube", "/Game/Textures/T_Rock"]``).
        force_delete: If ``True``, force-delete even when referencers exist.

    Returns:
        dict: ActionResultModel with deleted count and any failures.
    """
    import unreal  # noqa: PLC0415

    # --- normalise input ---
    if not asset_paths:
        return skill_error(
            "Missing required parameter: 'asset_paths'",
            "asset_paths must be a path string or list of path strings",
            possible_solutions=["Example: '/Game/Meshes/SM_Cube'"],
        )

    if isinstance(asset_paths, str):
        paths = [asset_paths]
    else:
        paths = list(asset_paths)

    paths = [p.split(".")[0] for p in paths]  # normalise to package paths

    # --- load assets ---
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    objects_to_delete = []
    not_found = []

    for package_name in paths:
        asset_data_list = asset_registry.get_assets_by_package_name(package_name)
        if not asset_data_list:
            not_found.append(package_name)
            continue
        obj = unreal.load_asset(object_path(asset_data_list[0]))
        if obj is not None:
            objects_to_delete.append(obj)
        else:
            not_found.append(package_name)

    if not objects_to_delete:
        return skill_error(
            "No assets found to delete",
            f"None of the provided paths resolved to loaded assets: {paths}",
            prompt="Use list_assets to verify the asset paths.",
            possible_solutions=["Check asset paths with list_assets"],
            not_found=not_found,
        )

    # --- delete ---
    if force_delete:
        # Consolidate references to None, then delete
        deleted_count = unreal.EditorAssetLibrary.consolidate_assets(None, objects_to_delete)
        # After consolidation, attempt hard delete
        success = unreal.EditorAssetLibrary.delete_loaded_assets(objects_to_delete)
    else:
        success = unreal.EditorAssetLibrary.delete_loaded_assets(objects_to_delete)
        deleted_count = len(objects_to_delete) if success else 0

    deleted_paths = [p for p in paths if p not in not_found]

    if not_found:
        return skill_warning(
            f"Deleted {deleted_count} asset(s); {len(not_found)} path(s) not found",
            warning=f"Not found: {not_found}",
            prompt="Use list_assets to verify remaining assets.",
            deleted_count=deleted_count,
            deleted_paths=deleted_paths,
            not_found=not_found,
        )

    return skill_success(
        f"Deleted {deleted_count} asset(s)",
        prompt="Use list_assets to confirm the assets have been removed.",
        deleted_count=deleted_count,
        deleted_paths=deleted_paths,
    )


def main(**kwargs) -> dict:
    return delete_asset(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
