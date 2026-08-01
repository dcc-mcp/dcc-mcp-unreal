"""Spawn a Chaos Geometry Collection actor in the active editor level."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def spawn_geometry_collection_actor(
    geometry_collection_path: str = "",
    location_x: float = 0.0,
    location_y: float = 0.0,
    location_z: float = 0.0,
    damage_threshold: float = 1000.0,
    label: str = "",
    **kwargs,
) -> dict:
    """Spawn a Geometry Collection actor configured for Chaos damage."""
    import unreal  # noqa: PLC0415

    if not geometry_collection_path or damage_threshold <= 0:
        return skill_error(
            "Invalid Geometry Collection actor settings",
            "geometry_collection_path is required and damage_threshold must be greater than zero",
        )
    spawn = getattr(unreal.DccMcpAutomationLibrary, "spawn_geometry_collection_actor", None)
    if spawn is None:
        return skill_error(
            "Chaos actor spawning is unavailable",
            "DccMcpAutomationLibrary.spawn_geometry_collection_actor is missing",
        )
    actor_name = spawn(
        geometry_collection_path,
        float(location_x),
        float(location_y),
        float(location_z),
        float(damage_threshold),
        label,
    )
    if not actor_name:
        return skill_error("Failed to spawn Geometry Collection actor", "Unreal spawning returned an empty actor name")
    return skill_success(
        f"Spawned Chaos actor '{actor_name}'",
        prompt="Run unreal_runtime__start_physics_simulation to validate physics in the editor.",
        actor_name=actor_name,
        geometry_collection_path=geometry_collection_path,
        location=[float(location_x), float(location_y), float(location_z)],
        damage_threshold=float(damage_threshold),
    )
