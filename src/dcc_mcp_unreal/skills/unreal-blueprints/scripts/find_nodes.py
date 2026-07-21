"""Find nodes in a Blueprint's event graph in Unreal Engine."""

from __future__ import annotations

from typing import Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def find_nodes(
    blueprint_name: str,
    node_type: Optional[str] = None,
    event_type: Optional[str] = None,
    **kwargs,
) -> dict:
    """Find nodes in a Blueprint's event graph.

    Args:
        blueprint_name: Name of the target Blueprint.
        node_type: Optional type filter (Event, Function, Variable, CustomEvent).
        event_type: Optional event type filter (BeginPlay, Tick, etc.).

    Returns:
        dict: ActionResultModel with list of found nodes.
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

    # Collect all nodes
    nodes = []
    for node in event_graph.get_all_nodes():
        node_class_name = node.get_class().get_name()
        node_guid = str(node.get_node_guid())
        node_title = node.get_node_title()

        # Apply type filter
        if node_type and node_type.lower() not in node_class_name.lower():
            continue

        # Apply event type filter
        if event_type and event_type.lower() not in node_title.lower():
            continue

        # Get pin info
        pins = []
        for pin in node.get_all_pins():
            pin_direction = "output" if pin.get_direction() == unreal.EdGraphPinDirection.EGPD_Output else "input"
            pins.append({
                "name": pin.get_name(),
                "direction": pin_direction,
                "type": str(pin.get_pin_type()),
            })

        nodes.append({
            "node_id": node_guid,
            "title": node_title,
            "type": node_class_name,
            "position": [node.get_editor_property("node_pos_x"), node.get_editor_property("node_pos_y")],
            "pins": pins,
        })

    return skill_success(
        f"Found {len(nodes)} node(s) in '{blueprint_name}'",
        prompt="Use node IDs with connect_nodes to wire them together.",
        blueprint_name=blueprint_name,
        nodes=nodes,
        count=len(nodes),
    )
