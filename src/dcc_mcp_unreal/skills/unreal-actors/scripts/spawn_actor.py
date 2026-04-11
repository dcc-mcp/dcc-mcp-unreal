"""Spawn an actor of a given class at a world position in Unreal Engine."""

from __future__ import annotations

from typing import Optional

from dcc_mcp_core.skill import skill_entry
from dcc_mcp_core.skill import skill_error
from dcc_mcp_core.skill import skill_success


@skill_entry
def spawn_actor(
    actor_class: str = "/Script/Engine.StaticMeshActor",
    location_x: float = 0.0,
    location_y: float = 0.0,
    location_z: float = 0.0,
    label: Optional[str] = None,
    **kwargs,
) -> dict:
    """Spawn an actor in the current Unreal Engine level.

    Args:
        actor_class: Full asset path of the actor class to spawn.
        location_x: World X position (cm).
        location_y: World Y position (cm).
        location_z: World Z position (cm).
        label: Optional display label for the spawned actor.

    Returns:
        dict: ActionResultModel with the spawned actor's name.
    """
    import unreal  # noqa: PLC0415

    location = unreal.Vector(location_x, location_y, location_z)
    rotation = unreal.Rotator(0, 0, 0)

    cls = unreal.load_class(None, actor_class)
    if cls is None:
        return skill_error(
            f"Actor class not found: {actor_class}",
            f"unreal.load_class returned None for '{actor_class}'",
            prompt="Check the actor class path and ensure the asset is loaded.",
            possible_solutions=[
                "Use the full asset path, e.g. '/Script/Engine.StaticMeshActor'",
                "Ensure the content browser asset exists and is loaded",
            ],
        )

    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(cls, location, rotation)
    actor_name = actor.get_name()

    if label:
        actor.set_actor_label(label)
        actor_name = label

    return skill_success(
        f"Spawned actor '{actor_name}' at ({location_x}, {location_y}, {location_z})",
        prompt=f"Use get_actor_transform to verify the position of '{actor_name}'.",
        actor_name=actor_name,
        actor_class=actor_class,
        location=[location_x, location_y, location_z],
    )


def main(**kwargs) -> dict:
    """Entry point; delegates to spawn_actor."""
    return spawn_actor(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
