"""Compile a Material and return shader compilation errors and warnings."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def compile_material(
    material_name: str,
    **kwargs,
) -> dict:
    """Compile a Material, applying all pending graph changes.

    Triggers the full HLSL shader compilation pipeline in Unreal Engine.
    Returns compilation errors and warnings if any.

    Args:
        material_name: Name of the Material to compile.

    Returns:
        ActionResultModel with compilation result including errors/warnings.
    """
    import unreal  # noqa: PLC0415

    if not material_name:
        return skill_error(
            "material_name is required",
            "Provide the name of the Material to compile.",
        )

    # Load the Material
    material_path = f"/Game/Materials/{material_name}"
    material = unreal.EditorAssetLibrary.load_asset(material_path)
    if material is None:
        return skill_error(
            f"Material not found: {material_name}",
            f"Could not load asset at '{material_path}'",
        )

    try:
        compiler_errors = unreal.MaterialEditingLibrary.recompile_material(material)
    except Exception as exc:
        return skill_error(
            f"Compilation failed for '{material_name}': {exc}",
            f"update_material_after_graph_change exception: {exc}",
            prompt="Check the Material graph in the editor for invalid connections or expressions.",
        )

    if compiler_errors is None:
        return skill_error(
            f"Could not verify compilation for Material '{material_name}'",
            "This Unreal version does not return compiler diagnostics from recompile_material.",
            prompt="Inspect the Material Editor compiler output before using this material.",
            material_name=material_name,
            material_path=material_path,
            verification="unavailable",
        )

    errors = [str(error) for error in compiler_errors if str(error).strip()]
    if errors:
        return skill_error(
            f"Material '{material_name}' compilation failed",
            "\n".join(errors),
            prompt="Fix the reported shader compiler errors and compile again.",
            material_name=material_name,
            material_path=material_path,
            errors=errors,
        )

    # Save after successful compilation
    unreal.EditorAssetLibrary.save_asset(material_path)

    return skill_success(
        f"Compiled Material '{material_name}' successfully",
        prompt="The Material is ready. Inspect with list_material_expressions or test in the viewport.",
        material_name=material_name,
        material_path=material_path,
        errors=[],
        warnings=[],
    )
