"""Compile a Blueprint in Unreal Engine."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def compile_blueprint(
    blueprint_name: str,
    **kwargs,
) -> dict:
    """Compile a Blueprint class, applying all pending graph changes.

    Args:
        blueprint_name: Name of the Blueprint to compile.

    Returns:
        dict: ActionResultModel with compilation result.
    """
    import unreal  # noqa: PLC0415

    # Load the Blueprint
    blueprint_path = f"/Game/Blueprints/{blueprint_name}"
    blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
    if blueprint is None:
        return skill_error(
            f"Blueprint not found: {blueprint_name}",
            f"Could not load asset at '{blueprint_path}'",
            prompt="Create the Blueprint first with create_blueprint_class.",
        )

    # Compile
    try:
        result = unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    except Exception as e:
        return skill_error(
            f"Compilation failed for '{blueprint_name}': {e}",
            f"compile_blueprint exception: {e}",
            prompt="Check the Blueprint for errors in the graph editor.",
        )

    if not result:
        return skill_error(
            f"Compilation returned errors for '{blueprint_name}'",
            "compile_blueprint returned False",
            prompt="Open the Blueprint in the editor to see compilation errors.",
        )

    # Save after successful compilation
    unreal.EditorAssetLibrary.save_asset(blueprint_path)

    return skill_success(
        f"Compiled Blueprint '{blueprint_name}' successfully",
        prompt="The Blueprint is ready to use. Spawn it with unreal_actors__spawn_actor.",
        blueprint_name=blueprint_name,
        blueprint_path=blueprint_path,
    )
