"""Find nodes in a Blueprint's event graph in Unreal Engine."""

from __future__ import annotations

from typing import Optional

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success


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
    normalized_name = str(blueprint_name or "").strip()
    if not normalized_name:
        return unreal_error(
            "Invalid Blueprint name",
            "blueprint_name must be a non-empty asset name",
            reason="invalid_argument",
            argument="blueprint_name",
        )

    blueprint_path = f"/Game/Blueprints/{normalized_name}"
    try:
        import unreal  # noqa: PLC0415

        blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
        if blueprint is None:
            return unreal_error(
                f"Blueprint not found: {normalized_name}",
                f"Could not load asset at '{blueprint_path}'",
                prompt="Create the Blueprint first with create_blueprint_class.",
                reason="not_found",
                blueprint_name=normalized_name,
            )

        from _blueprint_graph_api import get_graph, get_node_id, get_node_position, get_nodes  # noqa: PLC0415

        event_graph = get_graph(blueprint)
        if event_graph is None:
            return unreal_error(
                f"No event graph found in '{normalized_name}'",
                "No Blueprint graphs returned",
                prompt="Ensure the Blueprint has a valid event graph.",
                reason="event_graph_unavailable",
                blueprint_name=normalized_name,
            )

        nodes = []
        for node in get_nodes(event_graph):
            node_class_name = str(node.get_class().get_name())
            node_guid = get_node_id(node)
            node_title = str(unreal.BlueprintEditorLibrary.get_node_title(node))

            if node_type and node_type.casefold() not in node_class_name.casefold():
                continue
            if event_type and event_type.casefold() not in node_title.casefold():
                continue

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

        return unreal_success(
            f"Found {len(nodes)} node(s) in '{normalized_name}'",
            prompt="Use node IDs with connect_nodes to wire them together.",
            blueprint_name=normalized_name,
            nodes=nodes,
            count=len(nodes),
        )
    except Exception as exc:
        return unreal_from_exception(
            exc,
            f"Failed to inspect Blueprint '{normalized_name}'",
            reason="internal_error",
            blueprint_name=normalized_name,
        )
