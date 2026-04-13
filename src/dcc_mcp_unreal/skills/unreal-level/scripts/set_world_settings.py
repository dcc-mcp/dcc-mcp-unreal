"""Modify world settings of the current Unreal Engine level."""

from __future__ import annotations

from typing import Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def set_world_settings(
    gravity_z: Optional[float] = None,
    time_dilation: Optional[float] = None,
    kill_z: Optional[float] = None,
    **kwargs,
) -> dict:
    """Modify world settings for the current level.

    Only the provided arguments are changed; unspecified settings are left
    unchanged.  Pass ``None`` (or simply omit a parameter) to keep the
    current value.

    Args:
        gravity_z: World gravity in the Z direction (cm/s²).
            Default Unreal value is ``-980.0`` (Earth-like gravity).
            Use ``0.0`` for zero-gravity, positive values for inverted gravity.
        time_dilation: Global time dilation factor.  ``1.0`` is real time,
            ``0.5`` is half speed, ``2.0`` is double speed.
            Must be > 0.
        kill_z: The Z height below which actors are killed (cm).
            Actors that fall below this height receive kill damage.

    Returns:
        dict: ActionResultModel with the applied changes.
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

    # --- validate inputs ---
    if gravity_z is None and time_dilation is None and kill_z is None:
        return skill_error(
            "No settings provided",
            "At least one of gravity_z, time_dilation, or kill_z must be specified",
            possible_solutions=[
                "Pass gravity_z=-980.0 for Earth gravity",
                "Pass time_dilation=0.5 for half-speed",
                "Pass kill_z=-50000.0 to set the kill plane",
            ],
        )

    if time_dilation is not None and time_dilation <= 0:
        return skill_error(
            "Invalid time_dilation value",
            f"time_dilation must be > 0, got {time_dilation}",
            possible_solutions=["Use a positive value, e.g. 0.5, 1.0, or 2.0"],
        )

    def _safe_set(obj, prop: str, value) -> bool:
        try:
            obj.set_editor_property(prop, value)
            return True
        except Exception:
            return False

    applied: dict = {}
    errors: list = []

    if gravity_z is not None:
        if _safe_set(ws, "global_gravity_z", float(gravity_z)):
            applied["gravity_z"] = float(gravity_z)
        else:
            errors.append("gravity_z: could not set 'global_gravity_z'")

    if time_dilation is not None:
        if _safe_set(ws, "time_dilation", float(time_dilation)):
            applied["time_dilation"] = float(time_dilation)
        else:
            errors.append("time_dilation: could not set 'time_dilation'")

    if kill_z is not None:
        if _safe_set(ws, "kill_z", float(kill_z)):
            applied["kill_z"] = float(kill_z)
        else:
            errors.append("kill_z: could not set 'kill_z'")

    if not applied:
        return skill_error(
            "No world settings were applied",
            "; ".join(errors) if errors else "Unknown error",
            prompt="Check the Unreal Output Log for property errors.",
        )

    level_name = world.get_name()
    changes_summary = ", ".join(f"{k}={v}" for k, v in applied.items())

    # Mark level as dirty so the change will be saved
    try:
        world.mark_package_dirty()
    except Exception:
        pass

    return skill_success(
        f"Updated world settings for '{level_name}': {changes_summary}",
        prompt="Use get_world_settings to verify the changes, then save_level to persist them.",
        level_name=level_name,
        applied=applied,
        skipped_errors=errors if errors else None,
    )


def main(**kwargs) -> dict:
    return set_world_settings(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
