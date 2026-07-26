"""Set a MetaSound graph-input default using its declared type."""

from __future__ import annotations

from typing import Any

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal._metasound_builder import set_graph_input_default


@skill_entry
def set_metasound_parameter_default(
    asset_path: str,
    input_name: str,
    value: Any,
    **kwargs,
) -> dict:
    """Set a supported graph-input default and save the asset."""
    try:
        result = set_graph_input_default(asset_path, input_name, value)
    except Exception as exc:
        return skill_error(
            f"Failed to set MetaSound input {input_name!r}",
            str(exc),
        )
    return skill_success(f"Updated MetaSound input {input_name!r}", **result)
