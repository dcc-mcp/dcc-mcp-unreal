"""Spawn an actor of a given class at a world position in Unreal Engine."""

from __future__ import annotations

from typing import Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def spawn_actor(
    actor_class: str = "/Script/Engine.StaticMeshActor",
    static_mesh_path: str = "",
    location_x: float = 0.0,
    location_y: float = 0.0,
    location_z: float = 0.0,
    label: Optional[str] = None,
    **kwargs,
) -> dict:
    """Spawn an actor in the current Unreal Engine level.

    Args:
        actor_class: Full asset path of the actor class to spawn.
        static_mesh_path: Optional Static Mesh asset assigned after spawning.
        location_x: World X position (cm).
        location_y: World Y position (cm).
        location_z: World Z position (cm).
        label: Optional display label for the spawned actor.

    Returns:
        dict: ActionResultModel with the spawned actor's name.
    """
    import unreal  # noqa: PLC0415

    static_mesh = None
    if static_mesh_path:
        static_mesh = unreal.EditorAssetLibrary.load_asset(static_mesh_path)
        if not isinstance(static_mesh, unreal.StaticMesh):
            return skill_error(
                f"Static Mesh not found: {static_mesh_path}",
                "static_mesh_path must identify a StaticMesh asset",
            )

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
    if actor is None:
        return skill_error("Failed to spawn actor", f"Unreal rejected actor class '{actor_class}'")
    if static_mesh is not None:
        component = actor.get_component_by_class(unreal.StaticMeshComponent)
        if component is None:
            unreal.EditorLevelLibrary.destroy_actor(actor)
            return skill_error(
                "Spawned actor has no Static Mesh component",
                f"Actor class '{actor_class}' cannot accept static_mesh_path",
            )
        component.set_static_mesh(static_mesh)
    actor_name = actor.get_name()

    if label:
        actor.set_actor_label(label)
        actor_name = label

    bounds = None
    if static_mesh is not None:
        origin, extent = actor.get_actor_bounds(False)
        bounds = {
            "origin": [origin.x, origin.y, origin.z],
            "extent": [extent.x, extent.y, extent.z],
        }

    return skill_success(
        f"Spawned actor '{actor_name}' at ({location_x}, {location_y}, {location_z})",
        prompt=f"Use get_actor_transform to verify the position of '{actor_name}'.",
        actor_name=actor_name,
        actor_class=actor_class,
        static_mesh_path=static_mesh_path or None,
        location=[location_x, location_y, location_z],
        bounds=bounds,
    )
