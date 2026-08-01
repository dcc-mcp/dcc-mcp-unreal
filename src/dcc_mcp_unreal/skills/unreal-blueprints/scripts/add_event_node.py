"""Add an event node to a Blueprint's event graph in Unreal Engine."""

from __future__ import annotations

from typing import List, Optional

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

    # Load the Blueprint
    blueprint_path = f"/Game/Blueprints/{blueprint_name}"
    blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
    if blueprint is None:
        return skill_error(
            f"Blueprint not found: {blueprint_name}",
            f"Could not load asset at '{blueprint_path}'",
            prompt="Create the Blueprint first with create_blueprint_class.",
        )

    from _blueprint_graph_api import get_graph, get_graph_editor, get_node_id  # noqa: PLC0415

    event_graph = get_graph(blueprint)
    graph_editor = get_graph_editor(blueprint)
    if event_graph is None or graph_editor is None:
        return skill_error(
            f"No event graph found in '{blueprint_name}'",
            "No Blueprint graphs returned",
            prompt="Ensure the Blueprint has a valid event graph.",
        )

    # Create the event node
    # Map event names to Unreal event types
    event_node = _create_event_node_by_name(
        blueprint,
        graph_editor,
        event_name,
        node_position or [0, 0],
    )

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

    node_guid = get_node_id(event_node)
    layout_applied = node_position is None
    if layout_applied:
        from _blueprint_graph_api import layout_graph  # noqa: PLC0415

        layout_graph(event_graph)
        node_position = [
            unreal.BlueprintEditorLibrary.get_node_pos(event_node).x,
            unreal.BlueprintEditorLibrary.get_node_pos(event_node).y,
        ]

    unreal.BlueprintEditorLibrary.refresh_open_editors_for_blueprint(blueprint)

    return skill_success(
        f"Added event node '{event_name}' to '{blueprint_name}'",
        prompt=f"Node ID: {node_guid}. Use connect_nodes to wire it up.",
        blueprint_name=blueprint_name,
        event_name=event_name,
        node_id=node_guid,
        node_position=node_position,
        layout_applied=layout_applied,
    )


def _create_event_node_by_name(
    blueprint: "unreal.Blueprint",  # noqa: F821
    graph_editor: "unreal.BlueprintGraphEditor",  # noqa: F821
    event_name: str,
    node_position: List[float],
) -> "unreal.EdGraphNode":  # noqa: F821
    """Create an event node by name in the given graph."""
    import unreal  # noqa: PLC0415

    # Standard K2Node_Event for common events
    if event_name in ("ReceiveBeginPlay", "ReceiveTick", "ReceiveEndPlay", "ReceiveDestroyed"):
        return unreal.BlueprintEditorLibrary.add_event_override(
            blueprint,
            event_name,
            unreal.IntPoint(int(node_position[0]), int(node_position[1])),
        )

    # Custom event
    try:
        custom_event_node = graph_editor.add_custom_event_node(event_name)
        unreal.BlueprintEditorLibrary.set_node_pos(
            custom_event_node,
            unreal.IntPoint(int(node_position[0]), int(node_position[1])),
        )
        return custom_event_node
    except Exception:
        return None
