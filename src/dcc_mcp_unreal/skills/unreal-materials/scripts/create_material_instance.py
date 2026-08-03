"""Create a Material Instance asset from a parent Material Interface."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _is_material_interface(asset, unreal) -> bool:
    if isinstance(asset, unreal.MaterialInterface):
        return True
    get_class = getattr(asset, "get_class", None)
    asset_class = get_class() if callable(get_class) else None
    get_name = getattr(asset_class, "get_name", None)
    return callable(get_name) and get_name() in {
        "Material",
        "MaterialInstance",
        "MaterialInstanceConstant",
        "MaterialInstanceDynamic",
    }


@skill_entry
def create_material_instance(
    parent_material_path: str = "",
    destination_path: str = "/Game/Materials",
    instance_name: str = "",
    replace_existing: bool = False,
    **kwargs,
) -> dict:
    """Create a reusable Material Instance and set its parent."""
    import unreal  # noqa: PLC0415

    if not parent_material_path or not instance_name or not destination_path.startswith("/Game"):
        return skill_error(
            "Invalid Material Instance settings",
            "parent_material_path and instance_name are required; destination_path must be under /Game",
        )
    parent = unreal.EditorAssetLibrary.load_asset(parent_material_path)
    if parent is None or not _is_material_interface(parent, unreal):
        return skill_error("Material parent not found", f"'{parent_material_path}' is not a Material Interface")

    destination_path = destination_path.rstrip("/")
    object_path = f"{destination_path}/{instance_name}.{instance_name}"
    instance = unreal.EditorAssetLibrary.load_asset(object_path)
    if instance is not None:
        if not isinstance(instance, unreal.MaterialInstanceConstant) or not replace_existing:
            return skill_error(
                "Material Instance already exists",
                f"Set replace_existing=true to reuse '{object_path}'",
            )
    else:
        unreal.EditorAssetLibrary.make_directory(destination_path)
        instance = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            instance_name,
            destination_path,
            unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew(),
        )
    unreal.MaterialEditingLibrary.set_material_instance_parent(instance, parent)
    if not unreal.EditorAssetLibrary.save_loaded_asset(instance, only_if_is_dirty=False):
        return skill_error("Failed to save Material Instance", object_path)
    return skill_success(
        f"Created Material Instance '{object_path}'",
        prompt="Set parameters with unreal_materials__set_material_instance_parameters, then bind it with unreal_materials__assign_material.",
        instance_path=object_path,
        parent_material_path=parent_material_path,
    )
