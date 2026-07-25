"""Create a reusable Material Function asset in Unreal Engine."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def create_material_function(
    function_name: str,
    package_path: str = "/Game/Materials",
    description: str = "",
    **kwargs,
) -> dict:
    """Create a reusable Material Function asset.

    Material Functions encapsulate reusable node graphs with inputs and outputs.
    They can be called via MaterialFunctionCall nodes in any Material.

    Args:
        function_name: Name for the Material Function (e.g. "MF_Desaturate").
        package_path: Content Browser path (must start with /Game).
        description: Optional description text for the function.

    Returns:
        ActionResultModel with created function info.
    """
    import unreal  # noqa: PLC0415

    if not function_name or not package_path.startswith("/Game"):
        return skill_error(
            "Invalid Material Function settings",
            "function_name is required; package_path must start with /Game",
        )

    package_path = package_path.rstrip("/")
    full_path = f"{package_path}/{function_name}"

    # Check for existing asset
    if unreal.EditorAssetLibrary.does_asset_exist(full_path):
        return skill_error(
            f"Material Function already exists: {full_path}",
            "Delete the existing asset or choose a different name.",
        )

    # Ensure package directory
    if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
        unreal.EditorAssetLibrary.make_directory(package_path)

    # Create the Material Function
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialFunctionFactoryNew()
    func = asset_tools.create_asset(
        asset_name=function_name,
        package_path=package_path,
        asset_class=unreal.MaterialFunction,
        factory=factory,
    )

    if func is None:
        return skill_error(
            f"Failed to create Material Function '{function_name}'",
            "Asset creation returned None",
            prompt="Check that the name is unique and the path is writable.",
        )

    if description:
        func.set_editor_property("description", description)

    # Save
    unreal.EditorAssetLibrary.save_asset(full_path)

    return skill_success(
        f"Created Material Function '{function_name}' at {full_path}",
        prompt="Add expressions with add_material_expression (use target_kind=material_function), build your graph, then call it from a Material via MaterialFunctionCall.",
        function_name=function_name,
        function_path=full_path,
    )
