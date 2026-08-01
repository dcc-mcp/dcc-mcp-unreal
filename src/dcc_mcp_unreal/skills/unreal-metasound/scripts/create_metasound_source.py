"""Create a MetaSound Source through Unreal's reflected Builder API."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal._metasound_builder import create_source


@skill_entry
def create_metasound_source(
    asset_path: str,
    author: str = "dcc-mcp",
    output_format: str = "Mono",
    is_one_shot: bool = True,
    **kwargs,
) -> dict:
    """Create and persist a MetaSound Source asset."""
    try:
        result = create_source(asset_path, author, output_format, is_one_shot)
    except Exception as exc:
        return skill_error(
            f"Failed to create MetaSound Source at {asset_path}",
            str(exc),
            possible_solutions=[
                "Use a new /Game package path",
                "Enable the MetaSound and Python plugins",
                "Run the tool in Unreal Editor 5.4 or newer",
            ],
        )
    return skill_success(
        f"Created MetaSound Source at {asset_path}",
        prompt="Use the returned vertex handles to author and connect the graph.",
        **result,
    )
