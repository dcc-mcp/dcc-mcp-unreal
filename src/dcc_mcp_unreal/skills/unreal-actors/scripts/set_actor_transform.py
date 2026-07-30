"""Set the world-space transform of an actor in Unreal Engine."""

from __future__ import annotations

from typing import Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.api import find_level_actor


@skill_entry
def set_actor_transform(
    actor_name: str = "",
    location_x: Optional[float] = None,
    location_y: Optional[float] = None,
    location_z: Optional[float] = None,
    rotation_pitch: Optional[float] = None,
    rotation_yaw: Optional[float] = None,
    rotation_roll: Optional[float] = None,
    scale_x: Optional[float] = None,
    scale_y: Optional[float] = None,
    scale_z: Optional[float] = None,
    **kwargs,
) -> dict:
    """Set the world-space location, rotation, and/or scale of an actor.

    Only the components you provide are updated; omitted components retain their
    current values.

    Args:
        actor_name: The name of the actor to transform (as returned by list_actors).
        location_x: New world X position in cm (optional).
        location_y: New world Y position in cm (optional).
        location_z: New world Z position in cm (optional).
        rotation_pitch: New pitch in degrees (optional).
        rotation_yaw: New yaw in degrees (optional).
        rotation_roll: New roll in degrees (optional).
        scale_x: New X scale factor (optional).
        scale_y: New Y scale factor (optional).
        scale_z: New Z scale factor (optional).

    Returns:
        dict: ActionResultModel with the actor's updated transform.
    """
    import unreal  # noqa: PLC0415

    if not actor_name:
        return skill_error(
            "actor_name is required",
            "No actor name was provided",
            prompt="Use list_actors to find actor names.",
            possible_solutions=["Pass 'actor_name' as a non-empty string"],
        )

    target = find_level_actor(actor_name)

    if target is None:
        return skill_error(
            f"Actor not found: '{actor_name}'",
            f"No actor named '{actor_name}' exists in the current level",
            prompt="Use list_actors to see all available actor names.",
            possible_solutions=[
                "Check the actor name spelling (case-sensitive)",
                "Use list_actors to retrieve the correct name",
            ],
        )

    # Read current transform for any omitted components
    cur_loc = target.get_actor_location()
    cur_rot = target.get_actor_rotation()
    cur_scale = target.get_actor_scale3d()

    new_loc = unreal.Vector(
        location_x if location_x is not None else cur_loc.x,
        location_y if location_y is not None else cur_loc.y,
        location_z if location_z is not None else cur_loc.z,
    )
    new_rot = unreal.Rotator(
        pitch=rotation_pitch if rotation_pitch is not None else cur_rot.pitch,
        yaw=rotation_yaw if rotation_yaw is not None else cur_rot.yaw,
        roll=rotation_roll if rotation_roll is not None else cur_rot.roll,
    )
    new_scale = unreal.Vector(
        scale_x if scale_x is not None else cur_scale.x,
        scale_y if scale_y is not None else cur_scale.y,
        scale_z if scale_z is not None else cur_scale.z,
    )

    new_transform = unreal.Transform(new_loc, new_rot, new_scale)
    target.set_actor_transform(new_transform, sweep=False, teleport=True)

    return skill_success(
        f"Updated transform for actor '{actor_name}'",
        prompt=f"Use get_actor_transform to verify the new transform of '{actor_name}'.",
        actor_name=actor_name,
        location=[float(new_loc.x), float(new_loc.y), float(new_loc.z)],
        rotation=[float(new_rot.pitch), float(new_rot.yaw), float(new_rot.roll)],
        scale=[float(new_scale.x), float(new_scale.y), float(new_scale.z)],
    )
