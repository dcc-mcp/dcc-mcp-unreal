"""Delete an actor from the current Unreal Engine level by name."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def delete_actor(actor_name: str = "", **kwargs) -> dict:
    """Delete an actor from the current level by its name.

    Args:
        actor_name: The name of the actor to delete (as returned by list_actors).

    Returns:
        dict: ActionResultModel indicating success or failure.
    """
    import unreal  # noqa: PLC0415

    if not actor_name:
        return skill_error(
            "actor_name is required",
            "No actor name was provided",
            prompt="Use list_actors to find the actor name you want to delete.",
            possible_solutions=["Pass 'actor_name' as a non-empty string"],
        )

    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    target = next((a for a in all_actors if a.get_name() == actor_name), None)

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

    unreal.EditorLevelLibrary.destroy_actor(target)

    return skill_success(
        f"Deleted actor '{actor_name}'",
        prompt="Use list_actors to verify the actor has been removed.",
        actor_name=actor_name,
    )
