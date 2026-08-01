"""Validate a MetaSound asset with Unreal's registered validators."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal._metasound_builder import validate_graph


@skill_entry
def validate_metasound_graph(asset_path: str, **kwargs) -> dict:
    """Run Unreal Data Validation and report conclusive results only."""
    try:
        result = validate_graph(asset_path)
    except Exception as exc:
        return skill_error(f"Could not validate MetaSound at {asset_path}", str(exc))
    if not result["valid"]:
        details = "; ".join(result["errors"]) or result["validation_result"]
        return skill_error(
            f"MetaSound validation failed at {asset_path}",
            details,
        )
    return skill_success(f"MetaSound validation passed at {asset_path}", **result)
