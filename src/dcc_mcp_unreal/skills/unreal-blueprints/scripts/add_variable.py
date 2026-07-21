"""Add a member variable to a Blueprint in Unreal Engine."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def add_variable(
    blueprint_name: str,
    variable_name: str,
    variable_type: str,
    is_exposed: bool = False,
    **kwargs,
) -> dict:
    """Add a member variable to a Blueprint.

    Args:
        blueprint_name: Name of the target Blueprint.
        variable_name: Name for the new variable.
        variable_type: Type (Boolean, Integer, Float, Vector, String, etc.).
        is_exposed: Whether to expose the variable in the editor.

    Returns:
        dict: ActionResultModel with the added variable info.
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

    # Map type name to Unreal pin category
    type_map = {
        "boolean": ("bool", None),
        "bool": ("bool", None),
        "integer": ("int", None),
        "int": ("int", None),
        "float": ("real", "double"),
        "real": ("real", "double"),
        "double": ("real", "double"),
        "vector": ("struct", "Vector"),
        "rotator": ("struct", "Rotator"),
        "transform": ("struct", "Transform"),
        "string": ("string", None),
        "name": ("name", None),
        "text": ("text", None),
        "object": ("object", None),
        "class": ("class", None),
    }

    pin_category, pin_subcategory = type_map.get(
        variable_type.lower(), ("object", variable_type)
    )

    # Add the variable
    try:
        unreal.BlueprintEditorLibrary.add_member_variable(
            blueprint=blueprint,
            new_variable_name=variable_name,
            new_variable_type=pin_category,
        )
    except Exception as e:
        return skill_error(
            f"Failed to add variable '{variable_name}': {e}",
            f"add_member_variable exception: {e}",
            prompt="Check that the variable name is unique and the type is valid.",
            possible_solutions=[
                "Variable names must be unique within the Blueprint",
                "Supported types: Boolean, Integer, Float, Vector, String",
            ],
        )

    # Set exposure if requested
    if is_exposed:
        try:
            unreal.BlueprintEditorLibrary.set_blueprint_variable_expose(
                blueprint, variable_name, True
            )
        except Exception:
            pass  # Best effort for older UE versions

    return skill_success(
        f"Added variable '{variable_name}' ({variable_type}) to '{blueprint_name}'",
        prompt=f"Compile the Blueprint to apply changes: compile_blueprint('{blueprint_name}')",
        blueprint_name=blueprint_name,
        variable_name=variable_name,
        variable_type=variable_type,
        is_exposed=is_exposed,
    )
