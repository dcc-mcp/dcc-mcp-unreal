"""List all Material Expression nodes and their connections in a Material graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _load_material_asset(unreal, material_name: str, target_kind: str):
    """Load a Material or MaterialFunction asset by name.

    Args:
        unreal: The unreal module.
        material_name: Name of the asset.
        target_kind: 'material' or 'material_function'.

    Returns:
        Tuple of (asset, full_path) or (None, full_path) on failure.
    """
    package = "/Game/Materials"
    full_path = f"{package}/{material_name}"
    asset = unreal.EditorAssetLibrary.load_asset(full_path)
    if asset is None:
        alt = f"{package}/{material_name}.{material_name}"
        asset = unreal.EditorAssetLibrary.load_asset(alt)
        if asset is not None:
            full_path = alt
    return asset, full_path


def _is_valid_material_type(unreal, asset, target_kind: str) -> bool:
    """Return True if asset matches the expected target_kind."""
    if target_kind == "material":
        return isinstance(asset, unreal.Material)
    elif target_kind == "material_function":
        return isinstance(asset, unreal.MaterialFunction)
    return False


@skill_entry
def list_material_expressions(
    material_name: str,
    target_kind: str = "material",
    **kwargs,
) -> dict:
    """List all expression nodes and connections in a Material or Material Function graph.

    Args:
        material_name: Name of the Material or Material Function to inspect.
        target_kind: 'material' or 'material_function'.

    Returns:
        ActionResultModel with list of expression nodes and their connections.
    """
    import unreal  # noqa: PLC0415

    if target_kind not in ("material", "material_function"):
        return skill_error(
            f"Invalid target_kind: {target_kind}",
            "Must be 'material' or 'material_function'.",
        )

    if not material_name:
        return skill_error(
            "material_name is required",
            "Provide the name of the Material or Material Function.",
        )

    asset, full_path = _load_material_asset(unreal, material_name, target_kind)
    if asset is None:
        return skill_error(
            f"{target_kind.capitalize()} not found: {material_name}",
            f"Could not load asset at '{full_path}'",
        )

    if not _is_valid_material_type(unreal, asset, target_kind):
        actual = type(asset).__name__
        return skill_error(
            f"Asset '{material_name}' is a {actual}, not a {target_kind}",
            f"Expected {target_kind}, got {actual}",
        )

    expressions = []
    connections = []

    try:
        raw_expressions = asset.get_editor_property("expressions")
    except Exception:
        raw_expressions = []

    for i, expr in enumerate(raw_expressions or []):
        expr_type = type(expr).__name__
        expr_name = getattr(expr, "get_name", lambda: f"expr_{i}")()

        # Extract node position
        node_pos_x = 0
        node_pos_y = 0
        try:
            node_pos_x = int(expr.get_editor_property("material_expression_editor_x"))
            node_pos_y = int(expr.get_editor_property("material_expression_editor_y"))
        except Exception:
            pass

        # Extract description if any
        desc = ""
        try:
            desc = expr.get_editor_property("desc") or ""
        except Exception:
            pass

        node_info = {
            "index": i,
            "name": str(expr_name),
            "type": expr_type,
            "description": str(desc),
            "position": [node_pos_x, node_pos_y],
        }

        # For Custom HLSL nodes, include code snippet
        if "MaterialExpressionCustom" in expr_type:
            try:
                code = expr.get_editor_property("code") or ""
                node_info["hlsl_code_preview"] = code[:200] if code else ""
            except Exception:
                pass

        # For constants, include values
        if "Constant" in expr_type:
            for channel in "rgba":
                try:
                    val = expr.get_editor_property(channel)
                    if val is not None:
                        node_info.setdefault("values", {})[channel.upper()] = float(val)
                except Exception:
                    pass

        expressions.append(node_info)

        # Gather outgoing connections from this expression's pins
        for pin_idx in range(8):  # Check up to 8 output pins
            try:
                connected = unreal.MaterialEditingLibrary.get_material_expression_connected_output_pin(
                    expr, pin_idx
                )
                if connected is not None:
                    connections.append({
                        "from_node": str(expr_name),
                        "from_node_index": i,
                        "from_pin_index": pin_idx,
                        "to_node": str(connected["expression"].get_name() if connected.get("expression") else "unknown"),
                        "to_pin_index": connected.get("output_index", -1),
                    })
            except Exception:
                break

    return skill_success(
        f"Found {len(expressions)} expression(s) in '{material_name}'",
        material_name=material_name,
        material_path=full_path,
        target_kind=target_kind,
        expression_count=len(expressions),
        expressions=expressions,
        connections=connections,
    )
