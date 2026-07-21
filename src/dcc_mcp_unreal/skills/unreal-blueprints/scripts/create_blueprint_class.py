"""Create a new Blueprint class in Unreal Engine."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def create_blueprint_class(
    blueprint_name: str,
    parent_class: str = "Actor",
    package_path: str = "/Game/Blueprints",
    **kwargs,
) -> dict:
    """Create a new Blueprint class from a parent class.

    Args:
        blueprint_name: Name for the new Blueprint (e.g. "BP_MyActor").
        parent_class: Parent class name (e.g. "Actor", "Pawn", "Character").
        package_path: Content Browser path for the asset.

    Returns:
        dict: ActionResultModel with created Blueprint info.
    """
    import unreal  # noqa: PLC0415

    # Resolve parent class
    parent_class_path = f"/Script/Engine.{parent_class}"
    parent_cls = unreal.load_class(None, parent_class_path)
    if parent_cls is None:
        # Try common alternate paths
        alt_paths = [
            f"/Script/Engine.{parent_class}",
            f"/Script/CoreUObject.{parent_class}",
        ]
        for alt in alt_paths:
            parent_cls = unreal.load_class(None, alt)
            if parent_cls is not None:
                parent_class_path = alt
                break

    if parent_cls is None:
        return skill_error(
            f"Parent class not found: {parent_class}",
            f"unreal.load_class returned None for '{parent_class}'",
            prompt="Check the parent class name and try a fully qualified path.",
            possible_solutions=[
                "Use full path: '/Script/Engine.Actor'",
                "Verify the class name is correct (case-sensitive)",
            ],
        )

    # Ensure the package path exists
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
        unreal.EditorAssetLibrary.make_directory(package_path)

    # Create the Blueprint factory
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent_cls)

    full_path = f"{package_path}/{blueprint_name}"
    blueprint = asset_tools.create_asset(
        asset_name=blueprint_name,
        package_path=package_path,
        asset_class=unreal.Blueprint,
        factory=factory,
    )

    if blueprint is None:
        return skill_error(
            f"Failed to create Blueprint '{blueprint_name}'",
            "Asset creation returned None",
            prompt="Check that the name is unique and the path is writable.",
        )

    # Save the asset
    unreal.EditorAssetLibrary.save_asset(full_path)

    return skill_success(
        f"Created Blueprint '{blueprint_name}' at {full_path}",
        prompt=f"Use add_component_to_blueprint or add_event_node to build '{blueprint_name}'.",
        blueprint_name=blueprint_name,
        blueprint_path=full_path,
        parent_class=parent_class,
    )
