"""Get world settings from the current Unreal Engine level."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def get_world_settings(**kwargs) -> dict:
    """Get world settings for the current level.

    Returns key world settings including gravity, time dilation,
    kill-Z height, navigation mesh settings, and more.

    Returns:
        dict: ActionResultModel with world settings values.
    """
    import unreal  # noqa: PLC0415

    world = unreal.EditorLevelLibrary.get_editor_world()
    if world is None:
        return skill_error(
            "No editor world available",
            "EditorLevelLibrary.get_editor_world() returned None",
            prompt="Ensure Unreal Editor is fully loaded with an open level.",
        )

    ws = world.get_world_settings()
    if ws is None:
        return skill_error(
            "World settings not available",
            "world.get_world_settings() returned None",
        )

    def _safe_get(obj, prop: str, default=None):
        try:
            return obj.get_editor_property(prop)
        except Exception:
            return default

    settings = {
        # Physics
        "gravity_z": _safe_get(ws, "global_gravity_z", -980.0),
        "default_gravity_z": _safe_get(ws, "default_gravity_z", -980.0),
        # Time
        "time_dilation": _safe_get(ws, "time_dilation", 1.0),
        "matinee_time_dilation": _safe_get(ws, "demo_play_time_dilation", 1.0),
        # Kill volume
        "kill_z": _safe_get(ws, "kill_z", -100000.0),
        "kill_z_damage_type": str(_safe_get(ws, "kill_z_damage_type") or ""),
        # Navigation
        "nav_mesh_generation": _safe_get(ws, "navigation_system_config") is not None,
        # Gameplay
        "actor_class_overrides": [],
        # Lighting
        "lightmass_settings": None,
    }

    # Lightmass settings
    try:
        lm = _safe_get(ws, "lightmass_settings")
        if lm is not None:
            settings["lightmass_settings"] = {
                "static_lighting_level_scale": float(getattr(lm, "static_lighting_level_scale", 1.0)),
                "num_indirect_lighting_bounces": int(getattr(lm, "num_indirect_lighting_bounces", 3)),
                "num_sky_lighting_bounces": int(getattr(lm, "num_sky_lighting_bounces", 1)),
                "indirect_lighting_quality": float(getattr(lm, "indirect_lighting_quality", 1.0)),
                "indirect_lighting_smoothness": float(getattr(lm, "indirect_lighting_smoothness", 1.0)),
            }
    except Exception:
        pass

    level_name = world.get_name()

    return skill_success(
        f"World settings for '{level_name}'",
        prompt="Use set_world_settings to modify gravity, time dilation, or kill-Z.",
        level_name=level_name,
        **settings,
    )


def main(**kwargs) -> dict:
    return get_world_settings(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
