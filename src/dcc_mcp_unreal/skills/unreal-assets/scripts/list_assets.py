"""List assets in a Content Browser directory path."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry
from dcc_mcp_core.skill import skill_error
from dcc_mcp_core.skill import skill_success


@skill_entry
def list_assets(
    directory_path: str = "/Game",
    recursive: bool = True,
    asset_class_filter: str = "",
    **kwargs,
) -> dict:
    """List assets in a Content Browser directory.

    Args:
        directory_path: Content Browser path to list (e.g. ``"/Game"``,
            ``"/Game/Characters"``).
        recursive: If ``True``, include assets in subdirectories.
        asset_class_filter: Optional class name to filter results
            (e.g. ``"StaticMesh"``, ``"Texture2D"``, ``"Blueprint"``).

    Returns:
        dict: ActionResultModel with asset paths, names, and classes.
    """
    import unreal  # noqa: PLC0415

    # Normalise path — strip trailing slash
    directory_path = directory_path.rstrip("/") or "/Game"

    # Validate directory exists
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    if not asset_registry:
        return skill_error(
            "Asset Registry not available",
            "unreal.AssetRegistryHelpers.get_asset_registry() returned None",
            prompt="This usually means the editor is still loading. Try again in a moment.",
        )

    filter_obj = unreal.ARFilter(
        package_paths=[directory_path],
        recursive_paths=recursive,
    )
    asset_data_list = asset_registry.get_assets(filter_obj)

    # Apply optional class filter
    if asset_class_filter:
        filter_lower = asset_class_filter.lower()
        asset_data_list = [
            a for a in asset_data_list
            if filter_lower in str(a.asset_class_path.asset_name).lower()
        ]

    assets = []
    for asset_data in asset_data_list:
        assets.append({
            "name": str(asset_data.asset_name),
            "path": str(asset_data.package_name),
            "class": str(asset_data.asset_class_path.asset_name),
            "object_path": str(asset_data.object_path),
        })

    # Sort by path for deterministic output
    assets.sort(key=lambda a: a["path"])

    return skill_success(
        f"Found {len(assets)} asset(s) in '{directory_path}'",
        prompt="Use get_asset_info to inspect a specific asset, or import_asset to add new ones.",
        count=len(assets),
        directory=directory_path,
        recursive=recursive,
        class_filter=asset_class_filter or None,
        assets=assets,
    )


def main(**kwargs) -> dict:
    return list_assets(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main
    run_main(main)
