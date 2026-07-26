"""Add an exact registered MetaSound node class."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal._metasound_builder import add_node


@skill_entry
def add_metasound_node(
    asset_path: str,
    namespace: str,
    class_name: str,
    variant: str = "",
    major_version: int = 1,
    position_x: float = 0.0,
    position_y: float = 0.0,
    **kwargs,
) -> dict:
    """Add a node by its exact registered class identity."""
    try:
        result = add_node(
            asset_path,
            namespace,
            class_name,
            variant,
            major_version,
            position_x,
            position_y,
        )
    except Exception as exc:
        return skill_error(
            f"Failed to add MetaSound node {namespace}.{class_name}.{variant}",
            str(exc),
            possible_solutions=[
                "Use an exact MetaSound registry class name and variant",
                "For a sine oscillator use namespace=UE, class_name=Sine, variant=Audio",
            ],
        )
    return skill_success(
        f"Added MetaSound node {namespace}.{class_name}.{variant}",
        prompt="Connect the returned input/output handles with connect_metasound_nodes.",
        **result,
    )
