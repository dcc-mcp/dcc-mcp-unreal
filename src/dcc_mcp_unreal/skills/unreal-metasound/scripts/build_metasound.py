"""Build, validate, and persist a MetaSound asset."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal._metasound_builder import build_graph


@skill_entry
def build_metasound(asset_path: str, **kwargs) -> dict:
    """Overwrite the asset from its builder, validate it, and save it."""
    try:
        result = build_graph(asset_path)
    except Exception as exc:
        return skill_error(f"Failed to build MetaSound at {asset_path}", str(exc))
    return skill_success(f"Built and validated MetaSound at {asset_path}", **result)
