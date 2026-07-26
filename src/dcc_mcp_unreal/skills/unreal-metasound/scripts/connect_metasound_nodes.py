"""Connect exact MetaSound Builder vertex handles."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal._metasound_builder import connect_handles


@skill_entry
def connect_metasound_nodes(
    asset_path: str,
    output_handle: str,
    input_handle: str,
    **kwargs,
) -> dict:
    """Connect an output handle to an input handle in one MetaSound graph."""
    try:
        result = connect_handles(asset_path, output_handle, input_handle)
    except Exception as exc:
        return skill_error("Failed to connect MetaSound nodes", str(exc))
    message = "Connected MetaSound nodes" if result["changed"] else "MetaSound nodes were already connected"
    return skill_success(message, **result)
