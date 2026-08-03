"""Refresh generated output for Unreal PCG components."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def refresh_pcg(actor_name: str = "", **kwargs) -> dict:
    """Rebuild PCG components in the current editor level."""
    import unreal  # noqa: PLC0415

    world = unreal.EditorLevelLibrary.get_editor_world()
    if world is None:
        return skill_error(
            "No editor world available",
            "EditorLevelLibrary.get_editor_world() returned None",
            prompt="Open the target level before refreshing PCG.",
        )

    component_class = getattr(unreal, "PCGComponent", None)
    if component_class is None:
        return skill_error(
            "PCG Python API is unavailable",
            "unreal.PCGComponent is not exposed by this editor build",
            prompt="Enable the PCG plugin and restart Unreal Editor.",
        )

    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    if actor_name:
        actors = [actor for actor in actors if actor.get_name() == actor_name]

    refreshed = []
    for actor in actors:
        components = actor.get_components_by_class(component_class)
        for component in components:
            method = next(
                (
                    getattr(component, name, None)
                    for name in ("rebuild_generated", "generate")
                    if callable(getattr(component, name, None))
                ),
                None,
            )
            if method is None:
                continue
            method()
            refreshed.append({"actor_name": actor.get_name(), "method": method.__name__})

    if not refreshed:
        return skill_error(
            "No refreshable PCG components found",
            "No matching PCGComponent exposed a rebuild_generated or generate method",
            prompt="Check the actor name and ensure the level contains generated PCG actors.",
        )

    return skill_success(
        f"Refreshed {len(refreshed)} PCG component(s)",
        prompt="Save the level after verifying the regenerated output.",
        refreshed=refreshed,
        level_name=world.get_name(),
    )
