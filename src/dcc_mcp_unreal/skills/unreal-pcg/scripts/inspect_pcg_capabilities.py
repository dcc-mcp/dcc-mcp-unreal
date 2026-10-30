"""Inspect the current editor's PCG Python surface without mutating assets."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def inspect_pcg_capabilities(**kwargs) -> dict:
    """Return observed PCG capabilities separately from unverified execution."""
    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return skill_error(
            "Unreal Python API is unavailable",
            "Capability inspection requires a running Unreal Python host; no feature support was inferred.",
        )

    from dcc_mcp_unreal.pcg_capabilities import collect_pcg_capabilities  # noqa: PLC0415

    return skill_success(
        "PCG capability observation completed; native authoring behavior remains unverified.",
        prompt="Use the official MCP bridge separately to discover installed toolsets and exact schemas.",
        **collect_pcg_capabilities(unreal),
    )
