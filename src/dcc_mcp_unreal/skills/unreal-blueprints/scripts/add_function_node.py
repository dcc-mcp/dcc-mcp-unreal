"""Add a function call node to a Blueprint's event graph in Unreal Engine."""

from __future__ import annotations

from typing import List, Optional

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

    # Create the function call node
    function_path = function_name
    if not function_path.startswith("/"):
        parent_class = unreal.BlueprintEditorLibrary.get_blueprint_parent_class(blueprint)
        function_path = f"{parent_class.get_path_name()}.{function_name}"
    function_node = graph_editor.add_call_function_node(function_path)
    if function_node is None:
        return skill_error(
            f"Function not found: {function_name}",
            f"BlueprintGraphEditor.add_call_function_node failed for '{function_path}'",
            prompt="Use a native function path such as /Script/Engine.KismetSystemLibrary.PrintString.",
        )

    initial_position = node_position or [0, 0]
    unreal.BlueprintEditorLibrary.set_node_pos(
        function_node,
        unreal.IntPoint(int(initial_position[0]), int(initial_position[1])),
    )

    node_guid = get_node_id(function_node)
    layout_applied = node_position is None
    if layout_applied:
        from _blueprint_graph_api import layout_graph  # noqa: PLC0415

        layout_graph(event_graph)
        node_position = [
            unreal.BlueprintEditorLibrary.get_node_pos(function_node).x,
            unreal.BlueprintEditorLibrary.get_node_pos(function_node).y,
        ]

    return skill_success(
        f"Added function node '{function_name}' to '{blueprint_name}'",
        prompt=f"Node ID: {node_guid}. Connect it to event nodes with connect_nodes.",
        blueprint_name=blueprint_name,
        function_name=function_name,
        target=target,
        node_id=node_guid,
        node_position=node_position,
        layout_applied=layout_applied,
    )
