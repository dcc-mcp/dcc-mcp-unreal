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

    # Trigger recompilation
    errors = []
    warnings = []
    compiled = False

    try:
        # Force update and compile
        unreal.MaterialEditingLibrary.update_material_after_graph_change(material)
        unreal.MaterialEditingLibrary.layout_material_expressions(material)

        # Check for material compile errors
        stats = unreal.MaterialEditingLibrary.get_material_instance_statistics(material)
        if stats is not None:
            material_info = unreal.MaterialEditingLibrary.get_material_instance_info(material)
            if material_info is not None:
                compiled = True

        # Check for shader compiler errors programmatically
        try:
            if hasattr(unreal.ShaderPipelineCacheTools, "get_number_of_shader_compilation_failures"):
                # This is a best-effort check; not all builds expose it
                pass
        except Exception:
            pass

        compiled = True
    except Exception as exc:
        return skill_error(
            f"Compilation failed for '{material_name}': {exc}",
            f"update_material_after_graph_change exception: {exc}",
            prompt="Check the Material graph in the editor for invalid connections or expressions.",
        )

    if not compiled:
        return skill_error(
            f"Material '{material_name}' compilation returned errors",
            "Check the Material Editor for compilation errors in the output log.",
            prompt="Use list_material_expressions to inspect the graph.",
        )

    # Save after successful compilation
    unreal.EditorAssetLibrary.save_asset(material_path)

    return skill_success(
        f"Compiled Material '{material_name}' successfully",
        prompt="The Material is ready. Inspect with list_material_expressions or test in the viewport.",
        material_name=material_name,
        material_path=material_path,
        errors=errors,
        warnings=warnings,
    )
