"""Read-only procedural capability inspection."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def inspect_procedural_capabilities(**kwargs) -> dict:
    if kwargs:
        return skill_error("Invalid procedural capability request", "Unknown arguments", error_kind="invalid_input")
    try:
        import unreal  # noqa: PLC0415
        from dcc_mcp_unreal.procedural_workflows import inspect_capabilities  # noqa: PLC0415

        result = inspect_capabilities(unreal)
    except ImportError:
        return skill_error(
            "Unreal Python API is unavailable",
            "A running Unreal Editor is required for procedural capability inspection",
            error_kind="host_unavailable",
        )
    return skill_success("Inspected procedural capability prerequisites without mutation.", **result)
