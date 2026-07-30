"""Attach one level actor to another while preserving its world transform."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.api import find_level_actor


@skill_entry
def attach_actor(
    child_actor_name: str = "",
    parent_actor_name: str = "",
    keep_world_transform: bool = True,
    **kwargs,
) -> dict:
    """Attach a child actor to a parent actor."""
    import unreal  # noqa: PLC0415

    if not child_actor_name or not parent_actor_name:
        return skill_error(
            "child_actor_name and parent_actor_name are required",
            "Both actor names must identify actors in the current level",
        )
    if child_actor_name == parent_actor_name:
        return skill_error("An actor cannot be attached to itself", child_actor_name)

    child = find_level_actor(child_actor_name)
    parent = find_level_actor(parent_actor_name)
    if child is None or parent is None:
        missing = child_actor_name if child is None else parent_actor_name
        return skill_error(
            f"Actor not found: '{missing}'",
            "Use list_actors to retrieve exact actor names or labels",
        )

    if child.get_attach_parent_actor() == parent:
        return skill_success(
            f"Actor '{child_actor_name}' is already attached to '{parent_actor_name}'",
            child_actor_name=child_actor_name,
            parent_actor_name=parent_actor_name,
            keep_world_transform=keep_world_transform,
        )

    rule = unreal.AttachmentRule.KEEP_WORLD if keep_world_transform else unreal.AttachmentRule.KEEP_RELATIVE
    attached = child.attach_to_actor(parent, "", rule, rule, rule, False)
    if attached is False:
        return skill_error(
            f"Failed to attach '{child_actor_name}' to '{parent_actor_name}'",
            "Actor.attach_to_actor returned False",
        )

    return skill_success(
        f"Attached '{child_actor_name}' to '{parent_actor_name}'",
        prompt=f"Animate '{parent_actor_name}' to move the hierarchy.",
        child_actor_name=child_actor_name,
        parent_actor_name=parent_actor_name,
        keep_world_transform=keep_world_transform,
    )
