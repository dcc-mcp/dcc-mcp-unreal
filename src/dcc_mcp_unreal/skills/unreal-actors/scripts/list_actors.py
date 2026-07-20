"""List all actors in the current Unreal Engine level."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_success


@skill_entry
def list_actors(actor_class_filter: str = "", **kwargs) -> dict:
    """List actors in the current level, optionally filtered by class name.

    Args:
        actor_class_filter: Optional class name to filter by (e.g. "StaticMeshActor").

    Returns:
        dict: ActionResultModel with actor names and count.
    """
    import unreal  # noqa: PLC0415 — imported inside skill (not always available)

    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()

    if actor_class_filter:
        actors = [a for a in all_actors if actor_class_filter.lower() in a.get_class().get_name().lower()]
    else:
        actors = list(all_actors)

    actor_names = [a.get_name() for a in actors]

    return skill_success(
        f"Found {len(actor_names)} actor(s) in the level",
        prompt="Use spawn_actor to create new actors or get_actor_transform to inspect one.",
        count=len(actor_names),
        actors=actor_names,
        filter_applied=actor_class_filter or None,
    )
