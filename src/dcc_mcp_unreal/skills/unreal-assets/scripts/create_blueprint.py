"""Create a Blueprint asset from a native or Blueprint-generated class."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def create_blueprint(
    parent_class_path: str = "",
    destination_path: str = "/Game/Blueprints",
    blueprint_name: str = "",
    **kwargs,
) -> dict:
    import unreal  # noqa: PLC0415

    if not parent_class_path or not blueprint_name:
        return skill_error(
            "Missing required Blueprint parameters",
            "parent_class_path and blueprint_name are required",
        )

    destination_path = destination_path.rstrip("/") or "/Game/Blueprints"
    object_path = f"{destination_path}/{blueprint_name}.{blueprint_name}"
    existing = unreal.EditorAssetLibrary.load_asset(object_path)
    if existing is not None:
        if isinstance(existing, unreal.Blueprint):
            return skill_success(
                f"Blueprint already exists: {object_path}",
                object_path=object_path,
                created=False,
            )
        return skill_error(
            f"Asset already exists and is not a Blueprint: {object_path}",
            f"Loaded asset type: {type(existing).__name__}",
        )

    parent_class = unreal.load_class(None, parent_class_path)
    if parent_class is None:
        return skill_error(
            f"Parent class not found: {parent_class_path}",
            "Use a /Script/Module.Class or Blueprint generated-class path",
        )

    unreal.EditorAssetLibrary.make_directory(destination_path)
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent_class)
    blueprint = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        blueprint_name,
        destination_path,
        unreal.Blueprint,
        factory,
    )
    if blueprint is None:
        return skill_error(
            f"Failed to create Blueprint: {object_path}",
            "AssetTools.create_asset returned None",
        )
    if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False):
        return skill_error(
            f"Failed to save Blueprint: {object_path}",
            "EditorAssetLibrary.save_loaded_asset returned False",
        )

    return skill_success(
        f"Created Blueprint '{blueprint_name}'",
        prompt=f"Use get_asset_info to inspect '{object_path}'.",
        object_path=object_path,
        parent_class_path=parent_class_path,
        created=True,
    )


def main(**kwargs) -> dict:
    return create_blueprint(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
