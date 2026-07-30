"""Get metadata for a Content Browser asset."""

from __future__ import annotations

from _asset_data import configure_dependency_options
from _asset_data import object_path as asset_object_path
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def get_asset_info(
    asset_path: str = "",
    include_dependencies: bool = False,
    **kwargs,
) -> dict:
    """Get metadata for a Content Browser asset.

    Returns the asset class, package name, disk size, referencers, and
    optionally the list of assets this asset depends on.

    Args:
        asset_path: Content Browser object path or package path of the asset
            (e.g. ``"/Game/Meshes/SM_Cube"`` or
            ``"/Game/Meshes/SM_Cube.SM_Cube"``).
        include_dependencies: If ``True``, also return the list of assets
            that this asset directly depends on.

    Returns:
        dict: ActionResultModel with asset metadata.
    """
    import unreal  # noqa: PLC0415

    if not asset_path:
        return skill_error(
            "Missing required parameter: 'asset_path'",
            "asset_path must be a Content Browser path",
            possible_solutions=[
                "Use list_assets to find the correct path",
                "Example: '/Game/Meshes/SM_Cube'",
            ],
        )

    # Normalise: strip object suffix (everything after last '.')
    # /Game/Meshes/SM_Cube.SM_Cube  → /Game/Meshes/SM_Cube
    package_name = asset_path.split(".")[0]

    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    asset_data_list = asset_registry.get_assets_by_package_name(package_name)

    if not asset_data_list:
        return skill_error(
            f"Asset not found: {asset_path}",
            f"AssetRegistry found no data for package '{package_name}'",
            prompt="Use list_assets to browse available assets.",
            possible_solutions=[
                "Check the asset path with list_assets",
                "Ensure the asset hasn't been deleted or moved",
            ],
        )

    asset_data = asset_data_list[0]
    asset_name = str(asset_data.asset_name)
    asset_class = str(asset_data.asset_class_path.asset_name)
    object_path = asset_object_path(asset_data)

    # Retrieve dependencies if requested
    dependencies = []
    if include_dependencies:
        dep_options = configure_dependency_options(unreal.AssetRegistryDependencyOptions())

        dep_data = asset_registry.get_dependencies(package_name, dep_options)
        dependencies = [str(d) for d in dep_data]

    # Try to get disk size via asset metadata
    disk_size = None
    asset_obj = None
    try:
        asset_obj = unreal.load_asset(object_path)
        if asset_obj is not None:
            outer = asset_obj.get_outer()
            if outer is not None:
                disk_size = outer.get_file_size() if hasattr(outer, "get_file_size") else None
    except Exception:
        pass

    info: dict = {
        "name": asset_name,
        "class": asset_class,
        "package_name": package_name,
        "object_path": object_path,
    }
    if disk_size is not None:
        info["disk_size_bytes"] = disk_size
    if asset_obj is not None and isinstance(asset_obj, unreal.Texture):
        color_settings = asset_obj.get_editor_property("source_color_settings")
        info.update(
            srgb=bool(asset_obj.get_editor_property("srgb")),
            source_color_space=str(color_settings.get_editor_property("color_space"))
            .rsplit(".", 1)[-1]
            .split(":", 1)[0],
            source_encoding_override=str(color_settings.get_editor_property("encoding_override"))
            .rsplit(".", 1)[-1]
            .split(":", 1)[0],
        )
    if include_dependencies:
        info["dependencies"] = dependencies
        info["dependency_count"] = len(dependencies)

    return skill_success(
        f"Asset info for '{asset_name}' ({asset_class})",
        prompt="Use export_asset to export this asset, or delete_asset to remove it.",
        **info,
    )
