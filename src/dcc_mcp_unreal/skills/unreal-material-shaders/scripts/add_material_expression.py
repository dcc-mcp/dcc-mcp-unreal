"""Add a Material Expression node to a Material or Material Function graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

# 30+ supported expression types mapped to unreal.MaterialExpression* classes
_EXPRESSION_TYPE_MAP: dict[str, str] = {
    "Constant": "MaterialExpressionConstant",
    "Constant2Vector": "MaterialExpressionConstant2Vector",
    "Constant3Vector": "MaterialExpressionConstant3Vector",
    "Constant4Vector": "MaterialExpressionConstant4Vector",
    "TextureSample": "MaterialExpressionTextureSample",
    "TextureSampleParameter2D": "MaterialExpressionTextureSampleParameter2D",
    "TextureObject": "MaterialExpressionTextureObject",
    "Multiply": "MaterialExpressionMultiply",
    "Add": "MaterialExpressionAdd",
    "Subtract": "MaterialExpressionSubtract",
    "Divide": "MaterialExpressionDivide",
    "Lerp": "MaterialExpressionLinearInterpolate",
    "Fresnel": "MaterialExpressionFresnel",
    "Time": "MaterialExpressionTime",
    "Panner": "MaterialExpressionPanner",
    "Noise": "MaterialExpressionNoise",
    "MaterialFunctionCall": "MaterialExpressionMaterialFunctionCall",
    "Custom": "MaterialExpressionCustom",
    "VertexColor": "MaterialExpressionVertexColor",
    "WorldPosition": "MaterialExpressionWorldPosition",
    "CameraPositionWS": "MaterialExpressionCameraPositionWS",
    "CameraVectorWS": "MaterialExpressionCameraVectorWS",
    "PixelDepth": "MaterialExpressionPixelDepth",
    "SceneDepth": "MaterialExpressionSceneDepth",
    "SceneTexture": "MaterialExpressionSceneTexture",
    "SphereMask": "MaterialExpressionSphereMask",
    "Power": "MaterialExpressionPower",
    "OneMinus": "MaterialExpressionOneMinus",
    "Clamp": "MaterialExpressionClamp",
    "ComponentMask": "MaterialExpressionComponentMask",
    "AppendVector": "MaterialExpressionAppendVector",
    "CrossProduct": "MaterialExpressionCrossProduct",
    "DotProduct": "MaterialExpressionDotProduct",
    "Normalize": "MaterialExpressionNormalize",
    "Transform": "MaterialExpressionTransform",
    "TransformPosition": "MaterialExpressionTransformPosition",
    "StaticBool": "MaterialExpressionStaticBool",
    "StaticSwitch": "MaterialExpressionStaticSwitchParameter",
    "ScalarParameter": "MaterialExpressionScalarParameter",
    "VectorParameter": "MaterialExpressionVectorParameter",
}

_LOOSE_CASE_KEYS = {k.lower(): k for k in _EXPRESSION_TYPE_MAP}


def _resolve_expression_class(unreal, expression_type: str):
    """Resolve an expression type string to the corresponding Unreal class."""
    # Try exact match first
    class_name = _EXPRESSION_TYPE_MAP.get(expression_type)
    if class_name is None:
        # Try case-insensitive
        canonical = _LOOSE_CASE_KEYS.get(expression_type.lower())
        if canonical is not None:
            class_name = _EXPRESSION_TYPE_MAP[canonical]
    if class_name is None:
        return None
    return getattr(unreal, class_name, None)


def _apply_constant_params(expr, params: dict) -> None:
    """Apply value parameters to constant-typed expressions."""
    if "R" in params or "G" in params or "B" in params or "A" in params:
        r = float(params.get("R", 0.0))
        g = float(params.get("G", 0.0))
        b = float(params.get("B", 0.0))
        a = float(params.get("A", 1.0))
        if hasattr(expr, "set_editor_property"):
            if hasattr(expr, "r"):
                expr.set_editor_property("r", r)
            if hasattr(expr, "g"):
                expr.set_editor_property("g", g)
            if hasattr(expr, "b"):
                expr.set_editor_property("b", b)
            if hasattr(expr, "a"):
                expr.set_editor_property("a", a)
    elif "Value" in params:
        value = float(params["Value"])
        if hasattr(expr, "set_editor_property") and hasattr(expr, "r"):
            expr.set_editor_property("r", value)


def _apply_texture_sample_params(unreal, expr, params: dict) -> None:
    """Apply texture path to TextureSample expressions."""
    texture_path = params.get("Texture", params.get("texture", ""))
    if texture_path:
        texture = unreal.EditorAssetLibrary.load_asset(texture_path)
        if texture is not None and isinstance(texture, unreal.Texture):
            expr.set_editor_property("texture", texture)


def _apply_hlsl_custom_params(expr, params: dict) -> None:
    """Apply HLSL source and I/O declarations to CustomExpression nodes."""
    if "hlsl_code" in params:
        expr.set_editor_property("code", params["hlsl_code"])
    if "output_type" in params:
        output_type_map = {
            "CMOT_Float1": 0,
            "CMOT_Float2": 1,
            "CMOT_Float3": 2,
            "CMOT_Float4": 3,
            "CMOT_MaterialAttributes": 4,
        }
        expr.set_editor_property(
            "output_type",
            output_type_map.get(params["output_type"], 3),
        )


@skill_entry
def add_material_expression(
    material_name: str,
    expression_type: str,
    node_pos: list | None = None,
    params: dict | None = None,
    **kwargs,
) -> dict:
    """Add a Material Expression node to a Material graph.

    Args:
        material_name: Name of the target Material (e.g. "M_MyMaterial").
        expression_type: Expression class name (e.g. "Constant3Vector", "Multiply").
        node_pos: [X, Y] position in the graph (default [0, 0]).
        params: Expression-specific key-value parameters.

    Returns:
        ActionResultModel with created expression info.
    """
    import unreal  # noqa: PLC0415

    node_pos = node_pos or [0, 0]
    params = params or {}

    if not material_name or not expression_type:
        return skill_error(
            "material_name and expression_type are required",
            "Provide both a target material name and an expression type.",
        )

    if expression_type not in _EXPRESSION_TYPE_MAP and expression_type.lower() not in _LOOSE_CASE_KEYS:
        valid = ", ".join(sorted(_EXPRESSION_TYPE_MAP.keys()))
        return skill_error(
            f"Unknown expression type: {expression_type}",
            f"Supported types: {valid}",
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

    # Resolve expression class
    expr_cls = _resolve_expression_class(unreal, expression_type)
    if expr_cls is None:
        return skill_error(
            f"Could not resolve expression class for: {expression_type}",
            "The expression type may not be available in this Unreal Engine version.",
        )

    # Create the expression
    try:
        expression = unreal.MaterialEditingLibrary.create_material_expression(
            material, expr_cls, node_pos[0], node_pos[1]
        )
    except Exception as exc:
        return skill_error(
            f"Failed to add expression '{expression_type}' to '{material_name}'",
            f"create_material_expression exception: {exc}",
        )

    if expression is None:
        return skill_error(
            f"Failed to create expression '{expression_type}'",
            "MaterialEditingLibrary.create_material_expression returned None",
        )

    # Apply expression-specific parameters
    if expression_type in ("Constant", "Constant2Vector", "Constant3Vector", "Constant4Vector"):
        _apply_constant_params(expression, params)
    elif expression_type in ("TextureSample", "TextureSampleParameter2D", "TextureObject"):
        _apply_texture_sample_params(unreal, expression, params)
    elif expression_type == "Custom":
        _apply_hlsl_custom_params(expression, params)
    elif expression_type == "ScalarParameter" and "Value" in params:
        expression.set_editor_property("default_value", float(params["Value"]))
    elif expression_type == "VectorParameter" and "Value" in params:
        val = params["Value"]
        if isinstance(val, (list, tuple)) and 3 <= len(val) <= 4:
            expression.set_editor_property("default_value", unreal.LinearColor(
                float(val[0]), float(val[1]), float(val[2]), float(val[3]) if len(val) == 4 else 1.0
            ))

    # Save
    unreal.EditorAssetLibrary.save_asset(material_path)

    return skill_success(
        f"Added {expression_type} expression to '{material_name}'",
        prompt="Connect pins with connect_material_expressions, then compile.",
        material_name=material_name,
        expression_type=expression_type,
        node_pos=node_pos,
    )
