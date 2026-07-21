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

    # Get the event graph
    event_graphs = unreal.BlueprintEditorLibrary.get_blueprint_event_graphs(blueprint)
    if not event_graphs:
        return skill_error(
            f"No event graph found in '{blueprint_name}'",
            "No event graphs returned",
            prompt="Ensure the Blueprint has a valid event graph.",
        )

    event_graph = event_graphs[0]

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
        available = [p.get_name() for p in source_node.get_all_pins() if p.get_direction() == unreal.EdGraphPinDirection.EGPD_Output]
        return skill_error(
            f"Source pin '{source_pin}' not found on node {source_node_id}",
            f"Available output pins: {', '.join(available) if available else 'none'}",
            prompt=f"Available output pins: {', '.join(available) if available else 'none'}",
        )

    if target_pin_obj is None:
        available = [p.get_name() for p in target_node.get_all_pins() if p.get_direction() == unreal.EdGraphPinDirection.EGPD_Input]
        return skill_error(
            f"Target pin '{target_pin}' not found on node {target_node_id}",
            f"Available input pins: {', '.join(available) if available else 'none'}",
            prompt=f"Available input pins: {', '.join(available) if available else 'none'}",
        )

    # Make the connection
    try:
        source_pin_obj.make_link_to(target_pin_obj)
    except Exception as e:
        return skill_error(
            f"Failed to connect nodes: {e}",
            f"make_link_to failed: {e}",
            prompt="Check pin type compatibility.",
        )

    return skill_success(
        f"Connected '{source_node_id}.{source_pin}' -> '{target_node_id}.{target_pin}' in '{blueprint_name}'",
        prompt=f"Compile the Blueprint to apply changes: compile_blueprint('{blueprint_name}')",
        blueprint_name=blueprint_name,
        source_node_id=source_node_id,
        source_pin=source_pin,
        target_node_id=target_node_id,
        target_pin=target_pin,
    )


def _find_node_by_id(graph: "unreal.EdGraph", node_id: str) -> "unreal.EdGraphNode":
    """Find a node in the graph by its GUID string."""
    import unreal  # noqa: PLC0415

    for node in graph.get_all_nodes():
        if str(node.get_node_guid()) == node_id:
            return node
    return None


def _find_pin_by_name(
    node: "unreal.EdGraphNode",
    pin_name: str,
    is_output: bool = False,
) -> "unreal.EdGraphPin":
    """Find a pin on a node by name and direction."""
    import unreal  # noqa: PLC0415

    direction = unreal.EdGraphPinDirection.EGPD_Output if is_output else unreal.EdGraphPinDirection.EGPD_Input

    for pin in node.get_all_pins():
        if pin.get_direction() == direction and pin.get_name().lower() == pin_name.lower():
            return pin
    return None
