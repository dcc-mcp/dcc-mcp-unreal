"""Get information about the current Unreal Engine level."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_unreal.world_preflight import editor_world_error


@skill_entry
def get_level_info(**kwargs) -> dict:
    """Get current level name, actor count, and basic world info.

    Returns the level's package path, the number of actors in the persistent
    level, the world type (editor / game / PIE), and the current time of day
    if a sky light is present.

    Returns:
        dict: ActionResultModel with level metadata.
    """
    import unreal  # noqa: PLC0415

    world, world_error = editor_world_error(unreal, retry_tool="unreal_level__get_level_info")
    if world_error is not None:
        return world_error

    level_name = world.get_name()
    package_name = world.get_outer().get_name() if world.get_outer() else level_name

    # Count actors in the persistent level
    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    actor_count = len(all_actors)

    # Count actors by class
    class_counts: dict = {}
    for actor in all_actors:
        cls = actor.get_class().get_name()
        class_counts[cls] = class_counts.get(cls, 0) + 1

    # Top 10 most common classes
    top_classes = sorted(class_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # World type
    world_type = str(world.world_type) if hasattr(world, "world_type") else "unknown"

    # Current level streaming state
    streaming_levels = []
    try:
        for sl in world.streaming_levels:
            streaming_levels.append(
                {
                    "name": sl.get_name(),
                    "loaded": sl.is_level_loaded(),
                    "visible": sl.is_level_visible() if hasattr(sl, "is_level_visible") else None,
                }
            )
    except Exception:
        pass

    return skill_success(
        f"Level '{level_name}' — {actor_count} actor(s)",
        prompt="Use get_world_settings to inspect gravity and time dilation, or list_actors to enumerate actors.",
        level_name=level_name,
        package_name=package_name,
        actor_count=actor_count,
        world_type=world_type,
        top_actor_classes=dict(top_classes),
        streaming_level_count=len(streaming_levels),
        streaming_levels=streaming_levels,
    )
