"""Create a Custom HLSL expression node in a Material graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

_VALID_INPUT_TYPES = frozenset(
    {"float", "float2", "float3", "float4", "Texture2D", "TextureCube", "MaterialAttributes"}
)

_VALID_OUTPUT_TYPES = frozenset(
    {
        "CMOT_Float1",
        "CMOT_Float2",
        "CMOT_Float3",
        "CMOT_Float4",
        "CMOT_MaterialAttributes",
    }
)

_OUTPUT_TYPE_ATTRS = {
    "CMOT_Float1": "CMOT_FLOAT1",
    "CMOT_Float2": "CMOT_FLOAT2",
    "CMOT_Float3": "CMOT_FLOAT3",
    "CMOT_Float4": "CMOT_FLOAT4",
    "CMOT_MaterialAttributes": "CMOT_MATERIAL_ATTRIBUTES",
}


@skill_entry
def create_hlsl_node(
    material_name: str,
    hlsl_code: str,
    inputs: list | None = None,
    output_type: str = "CMOT_Float3",
    description: str = "",
    node_pos: list | None = None,
    **kwargs,
) -> dict:
    """Create a Custom HLSL expression node in a Material graph.

    The HLSL source code is stored as a string in the UE CustomExpression node.
    UE performs its own security checks during shader compilation — no HLSL
    execution happens on the Python side. This is a pure data-pass operation.

    Args:
        material_name: Name of the target Material.
        hlsl_code: HLSL source code for the custom expression body.
        inputs: List of input parameter dicts with 'name' and optional 'type'.
        output_type: Custom Material Output Type (CMOT_Float1..4, MaterialAttributes).
        description: Description for the custom node.
        node_pos: [X, Y] position in the graph.

    Returns:
        ActionResultModel with created custom node info.
    """
    import unreal  # noqa: PLC0415

    inputs = inputs or []
    node_pos = node_pos or [0, 0]

    if not material_name or not hlsl_code:
        return skill_error(
            "material_name and hlsl_code are required",
            "Provide a target material name and HLSL source code.",
        )

    if output_type not in _VALID_OUTPUT_TYPES:
        return skill_error(
            f"Invalid output_type: {output_type}",
            f"Must be one of: {', '.join(sorted(_VALID_OUTPUT_TYPES))}",
        )

    # Validate input spec
    for i, inp in enumerate(inputs):
        if not isinstance(inp, dict) or "name" not in inp:
            return skill_error(
                f"Invalid input at index {i}",
                "Each input must be a dict with at least a 'name' key.",
            )
        if not str(inp["name"]).strip():
            return skill_error(
                f"Invalid input at index {i}",
                "Custom HLSL input names must be non-empty.",
            )
        inp_type = inp.get("type", "float3")
        if inp_type not in _VALID_INPUT_TYPES:
            return skill_error(
                f"Invalid input type '{inp_type}' for '{inp['name']}'",
                f"Must be one of: {', '.join(sorted(_VALID_INPUT_TYPES))}",
            )

    # Load the Material
    material_path = f"/Game/Materials/{material_name}"
    material = unreal.EditorAssetLibrary.load_asset(material_path)
    if material is None:
        return skill_error(
            f"Material not found: {material_name}",
            f"Could not load asset at '{material_path}'",
            prompt="Create the Material first with create_material_graph.",
        )

    # Create the Custom HLSL expression
    try:
        custom_expr = unreal.MaterialEditingLibrary.create_material_expression(
            material,
            unreal.MaterialExpressionCustom,
            node_pos[0],
            node_pos[1],
        )
    except Exception as exc:
        return skill_error(
            f"Failed to create Custom HLSL node for '{material_name}'",
            f"create_material_expression exception: {exc}",
        )

    if custom_expr is None:
        return skill_error(
            "Failed to create Custom HLSL node",
            "MaterialEditingLibrary.create_material_expression returned None",
        )

    try:
        custom_expr.set_editor_property("code", hlsl_code)
        output_enum = getattr(unreal.CustomMaterialOutputType, _OUTPUT_TYPE_ATTRS[output_type], None)
        if output_enum is None:
            raise RuntimeError(f"Unreal does not expose output type {output_type}")
        custom_expr.set_editor_property("output_type", output_enum)

        if description:
            custom_expr.set_editor_property("description", description)

        custom_inputs = []
        for inp in inputs:
            custom_input = unreal.CustomInput()
            custom_input.set_editor_property("input_name", unreal.Name(str(inp["name"])))
            custom_inputs.append(custom_input)
        custom_expr.set_editor_property("inputs", custom_inputs)
    except Exception as exc:
        unreal.MaterialEditingLibrary.delete_material_expression(material, custom_expr)
        return skill_error(
            f"Failed to configure Custom HLSL node for '{material_name}'",
            str(exc),
        )

    # Save
    unreal.EditorAssetLibrary.save_asset(material_path)

    return skill_success(
        f"Created Custom HLSL node in '{material_name}'",
        prompt="Validate HLSL syntax with validate_hlsl_syntax, then compile with compile_material to check shader compilation.",
        material_name=material_name,
        output_type=output_type,
        inputs=[{"name": i["name"], "type": i.get("type", "float3")} for i in inputs],
        node_pos=node_pos,
    )
