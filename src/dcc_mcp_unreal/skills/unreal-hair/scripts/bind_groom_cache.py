"""Bind exact Groom assets to one exact GroomComponent."""

from __future__ import annotations

from _hair_runtime import component_state, load_typed
from dcc_mcp_core.skill import skill_entry, skill_error, skill_exception, skill_success


@skill_entry
def bind_groom_cache(
    component_path: str = "",
    groom_asset_path: str = "",
    groom_cache_path: str = "",
    running: bool = True,
    looping: bool = True,
    manual_tick: bool = False,
    **kwargs,
) -> dict:
    """Bind a Groom and optional Cache without actor-label discovery."""
    import unreal  # noqa: PLC0415

    try:
        component = load_typed(unreal, component_path, unreal.GroomComponent, "component_path")
        groom = load_typed(unreal, groom_asset_path, unreal.GroomAsset, "groom_asset_path")
        cache = (
            load_typed(unreal, groom_cache_path, unreal.GroomCache, "groom_cache_path") if groom_cache_path else None
        )
        component.set_groom_asset(groom)
        component.set_groom_cache(cache)
        component.set_editor_property("running", bool(running))
        component.set_editor_property("looping", bool(looping))
        component.set_editor_property("manual_tick", bool(manual_tick))
        return skill_success(
            "Bound Groom assets to the exact GroomComponent",
            prompt="Use get_groom_component_info to verify the binding and playback state.",
            **component_state(component),
        )
    except ValueError as exc:
        return skill_error("Invalid Groom binding target", str(exc))
    except Exception as exc:
        return skill_exception(exc, message="Failed to bind Groom assets")
