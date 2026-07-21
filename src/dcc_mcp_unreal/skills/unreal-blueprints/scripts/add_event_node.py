"""Add an event node to a Blueprint's event graph in Unreal Engine."""

from __future__ import annotations

from typing import Optional, List

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def add_event_node(
    blueprint_name: str,
    event_name: str,
    node_position: Optional[List[float]] = None,
    **kwargs,
) -> dict:
    """Add an event node to a Blueprint's event graph.

    Args:
        blueprint_name: Name of the target Blueprint.
        event_name: Event name. Use "ReceiveBeginPlay", "ReceiveTick", etc.
        node_position: Optional [X, Y] position in the graph.

    Returns:
        dict: ActionResultModel with the created node info.
    """
    import unreal  # noqa: PLC0415

    if node_position is None:
        node_position = [0, 0]

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

    # Create the event node
    # Map event names to Unreal event types
    event_node = _create_event_node_by_name(event_graph, event_name, node_position)

    if event_node is None:
        return skill_error(
            f"Failed to create event node '{event_name}' in '{blueprint_name}'",
            "_create_event_node_by_name returned None",
            prompt="Check the event name. Use 'ReceiveBeginPlay', 'ReceiveTick', etc.",
            possible_solutions=[
                "Standard events: ReceiveBeginPlay, ReceiveTick, ReceiveEndPlay",
                "Input events: ReceiveInputAction (requires input mapping)",
            ],
        )

    node_guid = str(event_node.get_node_guid())

    return skill_success(
        f"Added event node '{event_name}' to '{blueprint_name}'",
        prompt=f"Node ID: {node_guid}. Use connect_nodes to wire it up.",
        blueprint_name=blueprint_name,
        event_name=event_name,
        node_id=node_guid,
        node_position=node_position,
    )


def _create_event_node_by_name(
    event_graph: "unreal.EdGraph",
    event_name: str,
    node_position: List[float],
) -> "unreal.EdGraphNode":
    """Create an event node by name in the given graph."""
    import unreal  # noqa: PLC0415

    # Standard K2Node_Event for common events
    if event_name in ("ReceiveBeginPlay", "ReceiveTick", "ReceiveEndPlay", "ReceiveDestroyed"):
        event_node = unreal.K2Node_Event()
        event_graph.add_node(event_node)

        # Find the function reference
        event_node.event_reference.set_external_member(event_name, None)

        event_node.set_editor_property("node_pos_x", int(node_position[0]))
        event_node.set_editor_property("node_pos_y", int(node_position[1]))

        # Post-creation init
        unreal.BlueprintEditorLibrary.refresh_open_blueprint_nodes(blueprint=None)

        return event_node

    # Custom event
    try:
        custom_event_node = unreal.K2Node_CustomEvent()
        event_graph.add_node(custom_event_node)

        custom_event_node.set_editor_property("node_pos_x", int(node_position[0]))
        custom_event_node.set_editor_property("node_pos_y", int(node_position[1]))
        custom_event_node.set_editor_property("custom_function_name", event_name)

        return custom_event_node
    except Exception:
        return None
