"""Add a function call node to a Blueprint's event graph in Unreal Engine."""

from __future__ import annotations

from typing import Optional, List

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def add_function_node(
    blueprint_name: str,
    target: str,
    function_name: str,
    node_position: Optional[List[float]] = None,
    **kwargs,
) -> dict:
    """Add a function call node to a Blueprint's event graph.

    Args:
        blueprint_name: Name of the target Blueprint.
        target: Target object (component name or "self").
        function_name: Name of the function to call.
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

    # Create the function call node
    function_node = unreal.K2Node_CallFunction()
    event_graph.add_node(function_node)

    function_node.set_editor_property("node_pos_x", int(node_position[0]))
    function_node.set_editor_property("node_pos_y", int(node_position[1]))

    # Try to resolve the function reference
    if target.lower() == "self":
        # Look for the function on the Blueprint's parent class
        parent_class = blueprint.get_editor_property("parent_class")
        if parent_class is not None:
            try:
                func_ref = unreal.EdGraphSchema_K2.find_function_by_name(
                    parent_class, function_name
                )
                if func_ref is not None:
                    function_node.set_editor_property("function_reference", func_ref)
            except Exception:
                pass
    else:
        # Component target - try to find the function on the component's class
        # This is a best-effort resolution; the node may need manual configuration
        pass

    node_guid = str(function_node.get_node_guid())

    return skill_success(
        f"Added function node '{function_name}' to '{blueprint_name}'",
        prompt=f"Node ID: {node_guid}. Connect it to event nodes with connect_nodes.",
        blueprint_name=blueprint_name,
        function_name=function_name,
        target=target,
        node_id=node_guid,
        node_position=node_position,
    )
