"""Connect two Material Expression nodes in a Material graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

# Material property pins that connect directly to the material output
_MATERIAL_PROPERTY_ATTRS = {
    "BaseColor": "MP_BASE_COLOR",
    "Metallic": "MP_METALLIC",
    "Specular": "MP_SPECULAR",
    "Roughness": "MP_ROUGHNESS",
    "Anisotropy": "MP_ANISOTROPY",
    "EmissiveColor": "MP_EMISSIVE_COLOR",
    "Opacity": "MP_OPACITY",
    "OpacityMask": "MP_OPACITY_MASK",
    "Normal": "MP_NORMAL",
    "Tangent": "MP_TANGENT",
    "WorldPositionOffset": "MP_WORLD_POSITION_OFFSET",
    "SubsurfaceColor": "MP_SUBSURFACE_COLOR",
    "Refraction": "MP_REFRACTION",
    "AmbientOcclusion": "MP_AMBIENT_OCCLUSION",
    "PixelDepthOffset": "MP_PIXEL_DEPTH_OFFSET",
}


@skill_entry
def connect_material_expressions(
    material_name: str,
    source_expression: str,
    target_expression: str,
    target_pin: str,
    source_pin: str = "",
    **kwargs,
) -> dict:
    """Connect two expression nodes in a Material graph.

    Args:
        material_name: Name of the target Material.
        source_expression: Name/identifier of the source expression node.
        source_pin: Output pin name on the source (empty for default).
        target_expression: Name/identifier of the target expression node.
        target_pin: Input pin name on the target (e.g. "A", "BaseColor").

    Returns:
        ActionResultModel with connection info.
    """
    import unreal  # noqa: PLC0415

    if not all([material_name, source_expression, target_expression, target_pin]):
        return skill_error(
            "material_name, source_expression, target_expression, and target_pin are required",
            "Provide both source and target expression identifiers and the target pin name.",
        )

    # Load the Material
    material_path = f"/Game/Materials/{material_name}"
    material = unreal.EditorAssetLibrary.load_asset(material_path)
    if material is None:
        return skill_error(
            f"Material not found: {material_name}",
            f"Could not load asset at '{material_path}'",
        )

    # Resolve source expression — try by name first, then as integer index
    source_expr = _find_expression(material, source_expression)
    if source_expr is None:
        return skill_error(
            f"Source expression not found: {source_expression}",
            "Use list_material_expressions to see available nodes.",
            prompt="Check the expression name with list_material_expressions.",
        )

    # If target_pin maps to a material property, connect to material output
    if target_pin in _MATERIAL_PROPERTY_ATTRS:
        return _connect_to_material_output(unreal, material, material_path, source_expr, source_pin, target_pin)

    # Resolve target expression
    target_expr = _find_expression(material, target_expression)
    if target_expr is None:
        return skill_error(
            f"Target expression not found: {target_expression}",
            "Use list_material_expressions to see available nodes.",
        )

    # Connect source output pin → target input pin
    try:
        if source_pin:
            connected = unreal.MaterialEditingLibrary.connect_material_expressions(
                source_expr, source_pin, target_expr, target_pin
            )
        else:
            # Let the engine figure out the default output pin
            connected = unreal.MaterialEditingLibrary.connect_material_expressions(
                source_expr, "", target_expr, target_pin
            )
        if not connected:
            return skill_error(
                f"Failed to connect '{source_expression}' → '{target_expression}.{target_pin}'",
                "Unreal rejected the material expression connection.",
            )
    except Exception as exc:
        return skill_error(
            f"Failed to connect '{source_expression}' → '{target_expression}.{target_pin}'",
            f"connect_material_expressions exception: {exc}",
        )

    unreal.EditorAssetLibrary.save_asset(material_path)

    return skill_success(
        f"Connected {source_expression} → {target_expression}.{target_pin}",
        prompt="Compile the material with compile_material to see results.",
        material_name=material_name,
        source_expression=source_expression,
        source_pin=source_pin or "(default)",
        target_expression=target_expression,
        target_pin=target_pin,
    )


def _find_expression(material, key: str):
    """Find an expression node by name or integer index.

    Args:
        material: The loaded Material asset.
        key: Expression name (as displayed) or integer index as a string.

    Returns:
        The MaterialExpression object or None.
    """
    # Try integer index
    try:
        idx = int(key)
        expressions = material.get_editor_property("expressions")
        if 0 <= idx < len(expressions):
            return expressions[idx]
    except (ValueError, TypeError):
        pass

    # Try by name
    for expr in material.get_editor_property("expressions"):
        desc = getattr(expr, "desc", "")
        if desc == key:
            return expr
        # Also try asset_name / get_name
        obj_name = getattr(expr, "get_name", None)
        if callable(obj_name) and obj_name() == key:
            return expr

    return None


def _connect_to_material_output(unreal, material, material_path, source_expr, source_pin, property_name):
    """Connect an expression to a material output property pin."""
    try:
        property_enum = getattr(unreal.MaterialProperty, _MATERIAL_PROPERTY_ATTRS[property_name], None)
        if property_enum is None:
            return skill_error(
                f"Material property unavailable: {property_name}",
                f"Unreal does not expose {_MATERIAL_PROPERTY_ATTRS[property_name]} in this engine version.",
            )
        connected = unreal.MaterialEditingLibrary.connect_material_property(source_expr, source_pin, property_enum)
        if not connected:
            return skill_error(
                f"Failed to connect to Material {property_name}",
                "Unreal rejected the material property connection.",
            )

        unreal.EditorAssetLibrary.save_asset(material_path)
        return skill_success(
            f"Connected {source_expr.get_name()} → Material.{property_name}",
            prompt="Compile the material to apply changes.",
            material_name=material_path,
            source_expression=source_expr.get_name() if hasattr(source_expr, "get_name") else str(source_expr),
            target_pin=property_name,
        )
    except Exception as exc:
        return skill_error(
            f"Failed to connect to Material {property_name}",
            f"connect_material_property exception: {exc}",
        )
