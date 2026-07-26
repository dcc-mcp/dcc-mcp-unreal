"""Inspect an exact MetaSound node through public Builder methods."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal._metasound_builder import inspect_node


@skill_entry
def inspect_metasound_node(
    asset_path: str,
    node_handle: str,
    **kwargs,
) -> dict:
    """Return a node's registered version and reflected pins."""
    try:
        result = inspect_node(asset_path, node_handle)
    except Exception as exc:
        return skill_error("Failed to inspect MetaSound node", str(exc))
    return skill_success("Inspected MetaSound node", **result)
