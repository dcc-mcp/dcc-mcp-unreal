"""Read one exact GroomComponent binding and playback state."""

from __future__ import annotations

from _hair_runtime import component_state, load_typed
from dcc_mcp_core.skill import skill_entry, skill_error, skill_exception, skill_success


@skill_entry
def get_groom_component_info(component_path: str = "", **kwargs) -> dict:
    import unreal  # noqa: PLC0415

    try:
        component = load_typed(unreal, component_path, unreal.GroomComponent, "component_path")
        return skill_success("GroomComponent binding and playback state", **component_state(component))
    except ValueError as exc:
        return skill_error("Invalid GroomComponent target", str(exc))
    except Exception as exc:
        return skill_exception(exc, message="Failed to inspect GroomComponent")
