"""Read-only Unreal plugin capability preflight contracts."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple, TypedDict

CAPABILITY_PLUGIN_REQUIREMENTS: Mapping[str, Tuple[str, ...]] = {
    "static_groom_import": ("HairStrands", "AlembicHairImporter"),
    "usd_import": ("USDImporter",),
    "movie_render_queue": ("MovieRenderPipeline",),
}


class PluginNextAction(TypedDict, total=False):
    """Closed set of agent actions returned by plugin preflight."""

    action: str
    capability: str
    arguments: List[str]
    retry_tool: str
    retry_arguments: Dict[str, str]


class PluginPreflightResult(TypedDict):
    """JSON-safe typed result shared by the public tool and mutation guards."""

    capability: str
    required_plugins: List[str]
    enabled_plugins: List[str]
    missing_plugins: List[str]
    ready: bool
    next_action: PluginNextAction


def _enabled_plugin_names(unreal_module: Any) -> List[str]:
    """Read enabled plugin names through the adapter bridge or UE fallback."""
    library = getattr(unreal_module, "DccMcpAutomationLibrary", None)
    getter = getattr(library, "get_enabled_plugin_names", None)
    if not callable(getter):
        plugin_library = getattr(unreal_module, "PluginBlueprintLibrary", None)
        getter = getattr(plugin_library, "get_enabled_plugin_names", None)
    if not callable(getter):
        raise RuntimeError("Enabled plugin discovery is unavailable; update the DCC MCP Unreal plugin")
    return sorted({str(name) for name in getter()})


def plugin_preflight(unreal_module: Any, capability: str) -> PluginPreflightResult:
    """Return the deterministic plugin readiness result for one capability."""
    required: Sequence[str] | None = CAPABILITY_PLUGIN_REQUIREMENTS.get(capability)
    if required is None:
        raise ValueError("Unknown Unreal capability: {}".format(capability))

    enabled_names = set(_enabled_plugin_names(unreal_module))
    enabled = [name for name in required if name in enabled_names]
    missing = [name for name in required if name not in enabled_names]
    if missing:
        next_action: PluginNextAction = {
            "action": "restart_editor",
            "arguments": ["-EnablePlugins={}".format(",".join(required))],
            "retry_tool": "unreal_automation__preflight_plugins",
            "retry_arguments": {"capability": capability},
        }
    else:
        next_action = {"action": "proceed", "capability": capability}

    return PluginPreflightResult(
        capability=capability,
        required_plugins=list(required),
        enabled_plugins=enabled,
        missing_plugins=missing,
        ready=not missing,
        next_action=next_action,
    )


def require_plugins(unreal_module: Any, capability: str) -> Dict[str, Any] | None:
    """Return an ActionResult error when the capability cannot safely run."""
    from dcc_mcp_core.skill import skill_error  # noqa: PLC0415

    try:
        result = plugin_preflight(unreal_module, capability)
    except Exception as exc:
        return skill_error(
            "Unreal plugin preflight unavailable",
            str(exc),
            capability=capability,
            required_plugins=list(CAPABILITY_PLUGIN_REQUIREMENTS.get(capability, ())),
            enabled_plugins=[],
            missing_plugins=[],
            ready=False,
            next_action={"action": "update_adapter_plugin"},
        )
    if result["ready"]:
        return None
    return skill_error(
        "Required Unreal plugins are not enabled",
        "Missing plugins: {}".format(", ".join(result["missing_plugins"])),
        **result,
    )
