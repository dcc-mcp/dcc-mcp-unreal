"""Inspect required Unreal plugins without mutating the editor or project."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.plugin_preflight import CAPABILITY_PLUGIN_REQUIREMENTS, plugin_preflight


@skill_entry
def preflight_plugins(capability: str = "", **_kwargs) -> dict:
    """Return typed readiness and one deterministic next action."""
    if capability not in CAPABILITY_PLUGIN_REQUIREMENTS:
        return skill_error(
            "Unknown Unreal capability",
            "capability must be one of: {}".format(", ".join(CAPABILITY_PLUGIN_REQUIREMENTS)),
        )
    try:
        import unreal  # noqa: PLC0415

        result = plugin_preflight(unreal, capability)
    except Exception as exc:
        return skill_error(
            "Unreal plugin preflight unavailable",
            str(exc),
            capability=capability,
            required_plugins=list(CAPABILITY_PLUGIN_REQUIREMENTS[capability]),
            enabled_plugins=[],
            missing_plugins=[],
            ready=False,
            next_action={"action": "update_adapter_plugin"},
        )
    return skill_success(
        "Unreal capability is ready" if result["ready"] else "Unreal capability requires plugins",
        **result,
    )
