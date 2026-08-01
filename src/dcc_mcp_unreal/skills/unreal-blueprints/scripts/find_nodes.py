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

    from _blueprint_graph_api import get_graph, get_node_id, get_node_position, get_nodes  # noqa: PLC0415

    event_graph = get_graph(blueprint)
    if event_graph is None:
        return skill_error(
            f"No event graph found in '{blueprint_name}'",
            "No Blueprint graphs returned",
            prompt="Ensure the Blueprint has a valid event graph.",
        )

    # Collect all nodes
    nodes = []
    for node in get_nodes(event_graph):
        node_class_name = node.get_class().get_name()
        node_guid = get_node_id(node)
        node_title = unreal.BlueprintEditorLibrary.get_node_title(node)

        # Apply type filter
        if node_type and node_type.lower() not in node_class_name.lower():
            continue

        # Apply event type filter
        if event_type and event_type.lower() not in node_title.lower():
            continue

        # Get pin info
        pins = []
        for direction, node_pins in (
            ("input", unreal.BlueprintEditorLibrary.list_input_pins(node)),
            ("output", unreal.BlueprintEditorLibrary.list_output_pins(node)),
        ):
            pins.extend(
                {
                    "name": str(pin.get_pin_name()),
                    "direction": direction,
                    "type": str(pin.get_pin_type_display_string()),
                }
                for pin in node_pins
            )

        nodes.append(
            {
                "node_id": node_guid,
                "title": node_title,
                "type": node_class_name,
                "position": list(get_node_position(node)),
                "pins": pins,
            }
        )

    return skill_success(
        f"Found {len(nodes)} node(s) in '{blueprint_name}'",
        prompt="Use node IDs with connect_nodes to wire them together.",
        blueprint_name=blueprint_name,
        nodes=nodes,
        count=len(nodes),
    )
