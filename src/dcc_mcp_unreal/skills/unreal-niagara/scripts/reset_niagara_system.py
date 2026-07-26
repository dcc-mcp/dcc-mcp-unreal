"""Deactivate and reactivate a Niagara component to restart the simulation."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import find_level_actor, unreal_error, unreal_success


@skill_entry
def reset_niagara_system(
    actor_name: str,
    **kwargs,
) -> dict:
    """Reset a Niagara system by deactivating and reactivating it.

    Args:
        actor_name: Label or name of the Niagara actor in the level.

    Returns:
        ActionResultModel dict.
    """
    if not actor_name:
        return unreal_error(
            "actor_name is required",
            "Provide the label of a spawned Niagara actor.",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        actor = find_level_actor(actor_name)
        if actor is None:
            return unreal_error(
                "Niagara actor not found",
                f"No actor named '{actor_name}' in the current level.",
            )

        niagara_component = actor.get_component_by_class(unreal.NiagaraComponent)
        if niagara_component is None:
            return unreal_error(
                "No Niagara component found",
                f"Actor '{actor_name}' does not have a NiagaraComponent.",
            )

        # Deactivate and reactivate
        niagara_component.deactivate()
        niagara_component.activate(reset=True)

        return unreal_success(
            f"Reset Niagara system on '{actor_name}'",
            actor_name=actor_name,
            prompt="The particle simulation has restarted from its initial state.",
        )

    except Exception as exc:
        return unreal_error(
            "Failed to reset Niagara system",
            str(exc),
            actor_name=actor_name,
        )
