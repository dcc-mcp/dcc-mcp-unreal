"""Connect two nodes in a Blueprint's event graph in Unreal Engine."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def connect_nodes(
    blueprint_name: str,
    source_node_id: str,
    source_pin: str,
    target_node_id: str,
    target_pin: str,
    **kwargs,
) -> dict:
    """Connect two nodes in a Blueprint's event graph.

    Args:
        blueprint_name: Name of the target Blueprint.
        source_node_id: ID of the source node.
        source_pin: Name of the output pin on the source node.
        target_node_id: ID of the target node.
        target_pin: Name of the input pin on the target node.

    Returns:
        dict: ActionResultModel with connection result.
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

    from _blueprint_graph_api import get_graph  # noqa: PLC0415

    event_graph = get_graph(blueprint)
    if event_graph is None:
        return skill_error(
            f"No event graph found in '{blueprint_name}'",
            "No Blueprint graphs returned",
            prompt="Ensure the Blueprint has a valid event graph.",
        )

    # Find source and target nodes by GUID
    source_node = _find_node_by_id(event_graph, source_node_id)
    target_node = _find_node_by_id(event_graph, target_node_id)

    if source_node is None:
        return skill_error(
            f"Source node not found: {source_node_id}",
            "_find_node_by_id returned None",
            prompt="Use find_nodes to list available nodes.",
        )
    if target_node is None:
        return skill_error(
            f"Target node not found: {target_node_id}",
            "_find_node_by_id returned None",
            prompt="Use find_nodes to list available nodes.",
        )

    # Find the specific pins
    source_pin_obj = _find_pin_by_name(source_node, source_pin, is_output=True)
    target_pin_obj = _find_pin_by_name(target_node, target_pin, is_output=False)

    if source_pin_obj is None:
        available = [str(p.get_pin_name()) for p in unreal.BlueprintEditorLibrary.list_output_pins(source_node)]
        return skill_error(
            f"Source pin '{source_pin}' not found on node {source_node_id}",
            f"Available output pins: {', '.join(available) if available else 'none'}",
            prompt=f"Available output pins: {', '.join(available) if available else 'none'}",
        )

    if target_pin_obj is None:
        available = [str(p.get_pin_name()) for p in unreal.BlueprintEditorLibrary.list_input_pins(target_node)]
        return skill_error(
            f"Target pin '{target_pin}' not found on node {target_node_id}",
            f"Available input pins: {', '.join(available) if available else 'none'}",
            prompt=f"Available input pins: {', '.join(available) if available else 'none'}",
        )

    # Make the connection
    try:
        if not source_pin_obj.try_create_connection(target_pin_obj):
            raise ValueError("Unreal rejected the pin connection")
    except Exception as e:
        return skill_error(
            f"Failed to connect nodes: {e}",
            f"make_link_to failed: {e}",
            prompt="Check pin type compatibility.",
        )

    from _blueprint_graph_api import layout_graph  # noqa: PLC0415

    layout = layout_graph(event_graph)

    return skill_success(
        f"Connected '{source_node_id}.{source_pin}' -> '{target_node_id}.{target_pin}' in '{blueprint_name}'",
        prompt=f"Compile the Blueprint to apply changes: compile_blueprint('{blueprint_name}')",
        blueprint_name=blueprint_name,
        source_node_id=source_node_id,
        source_pin=source_pin,
        target_node_id=target_node_id,
        target_pin=target_pin,
        layout_applied=True,
        layout_node_count=layout["node_count"],
    )


def _find_node_by_id(graph: "unreal.EdGraph", node_id: str) -> "unreal.EdGraphNode":  # noqa: F821
    """Find a node in the graph by its GUID string."""

    from _blueprint_graph_api import get_node_id, get_nodes  # noqa: PLC0415

    for node in get_nodes(graph):
        if get_node_id(node) == node_id:
            return node
    return None


def _find_pin_by_name(
    node: "unreal.EdGraphNode",  # noqa: F821
    pin_name: str,
    is_output: bool = False,
) -> "unreal.EdGraphPin":  # noqa: F821
    """Find a pin on a node by name and direction."""
    import unreal  # noqa: PLC0415

    pins = (
        unreal.BlueprintEditorLibrary.list_output_pins(node)
        if is_output
        else unreal.BlueprintEditorLibrary.list_input_pins(node)
    )
    for pin in pins:
        if str(pin.get_pin_name()).lower() == pin_name.lower():
            return pin
    return None
