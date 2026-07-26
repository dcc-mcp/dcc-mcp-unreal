"""Add a typed input with Unreal's MetaSound Builder API."""

from __future__ import annotations

from typing import Any

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal._metasound_builder import add_graph_input


@skill_entry
def add_metasound_input(
    asset_path: str,
    input_name: str,
    value_type: str,
    default_value: Any,
    **kwargs,
) -> dict:
    """Add a Bool, Float, Int32, or String graph input."""
    try:
        result = add_graph_input(asset_path, input_name, value_type, default_value)
    except Exception as exc:
        return skill_error(
            f"Failed to add MetaSound input {input_name!r}",
            str(exc),
        )
    return skill_success(
        f"Added MetaSound input {input_name!r}",
        prompt="Use output_handle with connect_metasound_nodes.",
        **result,
    )
