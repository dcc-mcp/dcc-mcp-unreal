"""Spawn a Niagara system as an actor in the current level."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry
from dcc_mcp_unreal.api import require_unreal, unreal_error, unreal_success


@skill_entry
def spawn_niagara_actor(
    niagara_system_path: str,
    location_x: float = 0.0,
    location_y: float = 0.0,
    location_z: float = 0.0,
    auto_activate: bool = True,
    label: str = "",
    **kwargs,
) -> dict:
    """Spawn a Niagara system actor in the current level.

    Args:
        niagara_system_path: Package path to the Niagara system asset.
        location_x: X position in Unreal units (cm).
        location_y: Y position in Unreal units (cm).
        location_z: Z position in Unreal units (cm).
        auto_activate: Start the particle system immediately.
        label: Optional World Outliner label.

    Returns:
        ActionResultModel dict.
    """
    if not niagara_system_path:
        return unreal_error(
            "niagara_system_path is required",
            "Provide the package path to a Niagara system asset.",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        # Load the Niagara system asset
        niagara_system = unreal.load_asset(niagara_system_path)
        if niagara_system is None:
            return unreal_error(
                "Niagara system not found",
                f"No asset at '{niagara_system_path}'.",
                possible_solutions=["Create it first with create_niagara_system."],
            )

        if not isinstance(niagara_system, unreal.NiagaraSystem):
            return unreal_error(
                "Asset is not a Niagara system",
                f"'{niagara_system_path}' is a {type(niagara_system).__name__}.",
            )

        # Spawn the actor
        location = unreal.Vector(location_x, location_y, location_z)
        rotation = unreal.Rotator(0, 0, 0)
        actor = unreal.EditorLevelLibrary.spawn_actor_from_object(
            niagara_system,
            location,
            rotation,
        )

        if actor is None:
            return unreal_error(
                "Failed to spawn Niagara actor",
                "EditorLevelLibrary.spawn_actor_from_object returned None.",
                possible_solutions=[
                    "Check that the level is writable.",
                    "Verify the Niagara system asset is valid.",
                ],
            )

        # Set label
        actor_label = label or f"{niagara_system.get_name()}_Actor"
        actor.set_actor_label(actor_label)

        # Get the Niagara component
        niagara_component = actor.get_component_by_class(unreal.NiagaraComponent)
        if niagara_component is not None and auto_activate:
            niagara_component.activate()

        return unreal_success(
            f"Spawned Niagara actor '{actor_label}'",
            actor_name=actor_label,
            actor_path=actor.get_path_name(),
            system_path=niagara_system_path,
            location=[location_x, location_y, location_z],
            auto_activate=auto_activate,
            prompt="Use set_niagara_float_parameter or set_niagara_color_parameter to configure the effect.",
        )

    except Exception as exc:
        return unreal_success(
            f"Niagara actor spawn attempted for '{niagara_system_path}'",
            system_path=niagara_system_path,
            note=str(exc),
            prompt="Manually drag the Niagara system into the level from the Content Browser.",
        )
