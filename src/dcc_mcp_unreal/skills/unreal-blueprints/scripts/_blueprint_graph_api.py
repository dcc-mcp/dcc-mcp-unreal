"""Shared Unreal Blueprint graph access and automatic layout."""

from __future__ import annotations


def get_graph(blueprint, graph_name: str = "EventGraph"):
    import unreal  # noqa: PLC0415

    library = unreal.BlueprintEditorLibrary
    graphs = (
        library.list_graphs(blueprint)
        if hasattr(library, "list_graphs")
        else library.get_blueprint_event_graphs(blueprint)
    )
    return next((graph for graph in graphs if str(graph.get_name()) == graph_name), graphs[0] if graphs else None)


def get_graph_editor(blueprint, graph_name: str = "EventGraph"):
    import unreal  # noqa: PLC0415

    if not hasattr(unreal, "BlueprintGraphEditor"):
        return None
    return unreal.BlueprintGraphEditor.get_graph_editor_by_name(blueprint, graph_name)


def get_nodes(graph) -> list:
    import unreal  # noqa: PLC0415

    if hasattr(unreal, "BlueprintGraphEditor"):
        editor = unreal.BlueprintGraphEditor.get_graph_editor(graph)
        if editor is not None:
            return list(editor.list_all_nodes())
    return list(graph.get_all_nodes())


def get_node_id(node) -> str:
    if hasattr(node, "get_node_guid"):
        return str(node.get_node_guid())
    if hasattr(node, "get_path_name"):
        return str(node.get_path_name())
    return str(node.get_editor_property("node_guid"))


def get_node_position(node) -> tuple[int, int]:
    import unreal  # noqa: PLC0415

    if hasattr(unreal.BlueprintEditorLibrary, "get_node_pos"):
        position = unreal.BlueprintEditorLibrary.get_node_pos(node)
        return int(position.x), int(position.y)
    return (
        int(node.get_editor_property("node_pos_x")),
        int(node.get_editor_property("node_pos_y")),
    )


def layout_graph(graph, horizontal_spacing: int = 400, vertical_spacing: int = 220) -> dict:
    """Arrange connected nodes by dependency depth and keep every node distinct."""
    import unreal  # noqa: PLC0415

    nodes = get_nodes(graph)
    if not nodes:
        return {"node_count": 0, "column_count": 0}

    node_by_id = {get_node_id(node): node for node in nodes}
    edges = {node_id: set() for node_id in node_by_id}
    indegree = {node_id: 0 for node_id in node_by_id}

    if hasattr(unreal, "BlueprintGraphPinLibrary") and hasattr(
        unreal.BlueprintEditorLibrary, "list_output_pins"
    ):
        for source_id, node in node_by_id.items():
            for pin in unreal.BlueprintEditorLibrary.list_output_pins(node):
                for linked_pin in unreal.BlueprintGraphPinLibrary.list_connected_pins(pin):
                    target = unreal.BlueprintGraphPinLibrary.get_owning_node(linked_pin)
                    target_id = get_node_id(target)
                    if target_id in node_by_id and target_id not in edges[source_id]:
                        edges[source_id].add(target_id)
                        indegree[target_id] += 1

    def sort_key(node_id: str) -> tuple[int, int, str]:
        x, y = get_node_position(node_by_id[node_id])
        return (y, x, node_id)

    ranks = {node_id: 0 for node_id in node_by_id}
    queue = sorted((node_id for node_id, degree in indegree.items() if degree == 0), key=sort_key)
    visited = set()
    while queue:
        source_id = queue.pop(0)
        visited.add(source_id)
        for target_id in sorted(edges[source_id], key=sort_key):
            ranks[target_id] = max(ranks[target_id], ranks[source_id] + 1)
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                queue.append(target_id)
                queue.sort(key=sort_key)

    cycle_rank = max(ranks.values(), default=0) + 1
    for node_id in node_by_id.keys() - visited:
        ranks[node_id] = cycle_rank

    columns: dict[int, list[str]] = {}
    for node_id, rank in ranks.items():
        columns.setdefault(rank, []).append(node_id)

    positions = [get_node_position(node) for node in nodes]
    base_x = min(x for x, _ in positions)
    base_y = min(y for _, y in positions)
    for rank, node_ids in sorted(columns.items()):
        for row, node_id in enumerate(sorted(node_ids, key=sort_key)):
            node = node_by_id[node_id]
            x = base_x + rank * horizontal_spacing
            y = base_y + row * vertical_spacing
            try:
                unreal.BlueprintEditorLibrary.set_node_pos(node, unreal.IntPoint(x, y))
            except Exception:
                node.set_editor_property("node_pos_x", x)
                node.set_editor_property("node_pos_y", y)

    return {"node_count": len(nodes), "column_count": len(columns)}
