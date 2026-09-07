"""Plan or independently authorize configuration of capability plugins."""

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.plugin_configuration import apply_plugin_configuration, plugin_configuration_plan
from dcc_mcp_unreal.plugin_preflight import CAPABILITY_PLUGIN_REQUIREMENTS


@skill_entry
def configure_plugins(capability="", mode="plan", expected_sha256="", **_kwargs):
    if capability not in CAPABILITY_PLUGIN_REQUIREMENTS or mode not in ("plan", "apply"):
        return skill_error("Invalid plugin configuration request", "Use a supported capability and plan/apply mode")
    try:
        import unreal  # noqa: PLC0415

        if mode == "plan":
            return skill_success(
                "Plugin configuration plan; no changes made", **plugin_configuration_plan(unreal, capability)
            )
        if not expected_sha256:
            return skill_error("Missing expected_sha256", "Read a plan first; apply requires independent user consent")
        result = apply_plugin_configuration(unreal, capability, expected_sha256)
        if result["status"] not in ("configured", "unchanged"):
            return skill_error("Plugin configuration was not applied", result["status"], **result)
        return skill_success("Plugin descriptor configuration complete", **result)
    except Exception as exc:
        return skill_error("Plugin configuration unavailable", str(exc))
