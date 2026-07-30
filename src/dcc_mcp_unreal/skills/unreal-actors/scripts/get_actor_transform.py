"""Get the world-space transform of an actor in Unreal Engine."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.api import find_level_actor


@skill_entry
def get_actor_transform(actor_name: str = "", **kwargs) -> dict:
    """Get the world-space location, rotation, and scale of an actor.

    Args:
        actor_name: The name of the actor (as returned by list_actors).

    Returns:
        dict: ActionResultModel with location, rotation, and scale as float lists.
    """
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

    loc = target.get_actor_location()
    rot = target.get_actor_rotation()
    scale = target.get_actor_scale3d()

    return skill_success(
        f"Got transform for actor '{actor_name}'",
        prompt=f"Use set_actor_transform to move '{actor_name}' to a new position.",
        actor_name=actor_name,
        location=[float(loc.x), float(loc.y), float(loc.z)],
        rotation=[float(rot.pitch), float(rot.yaw), float(rot.roll)],
        scale=[float(scale.x), float(scale.y), float(scale.z)],
    )
