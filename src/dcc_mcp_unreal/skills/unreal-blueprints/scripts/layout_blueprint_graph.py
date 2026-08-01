"""Lay out nodes in a Blueprint graph from left to right."""

from __future__ import annotations

from _blueprint_graph_api import get_graph, layout_graph
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def layout_blueprint_graph(
    blueprint_name: str,
    graph_name: str = "EventGraph",
    horizontal_spacing: int = 400,
    vertical_spacing: int = 220,
    **kwargs,
) -> dict:
    """Automatically lay out one graph in a Blueprint."""
    import unreal  # noqa: PLC0415

    blueprint_path = f"/Game/Blueprints/{blueprint_name}"
    blueprint = unreal.EditorAssetLibrary.load_asset(blueprint_path)
    if blueprint is None:
        return skill_error(
            f"Blueprint not found: {blueprint_name}",
            f"Could not load asset at '{blueprint_path}'",
            prompt="Create the Blueprint first with create_blueprint_class.",
        )

    graph = get_graph(blueprint, graph_name)
    if graph is None:
        return skill_error(
            f"Graph not found: {graph_name}",
            "No Blueprint graphs returned",
            prompt="Ensure the Blueprint has a valid graph.",
        )

    result = layout_graph(graph, int(horizontal_spacing), int(vertical_spacing))
    unreal.BlueprintEditorLibrary.refresh_open_editors_for_blueprint(blueprint)
    return skill_success(
        f"Laid out {result['node_count']} node(s) in '{blueprint_name}.{graph_name}'",
        blueprint_name=blueprint_name,
        graph_name=graph_name,
        **result,
    )


def main(**kwargs):
    return layout_blueprint_graph(**kwargs)
