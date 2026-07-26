"""Set a float parameter on a Niagara component by name."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_success


@skill_entry
def set_niagara_float_parameter(
    actor_name: str,
    parameter_name: str,
    value: float,
    **kwargs,
) -> dict:
    """Set a float parameter on a Niagara component.

    Args:
        actor_name: Label or name of the Niagara actor in the level.
        parameter_name: Name of the exposed float parameter.
        value: Float value to set.

    Returns:
        ActionResultModel dict.
    """
    if not actor_name or not parameter_name:
        return unreal_error(
            "Missing required parameters",
            "actor_name and parameter_name are required",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        # Find the actor
        actor = unreal.EditorLevelLibrary.find_actor_by_label_in_level(
            unreal.EditorLevelLibrary.get_editor_world(),
            actor_name,
        )
        if actor is None:
            all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
            matches = [a for a in all_actors if a.get_name() == actor_name or a.get_actor_label() == actor_name]
            if not matches:
                return unreal_error(
                    "Niagara actor not found",
                    f"No actor named '{actor_name}' in the current level.",
                    possible_solutions=["Spawn it first with spawn_niagara_actor."],
                )
            actor = matches[0]

        # Get the Niagara component
        niagara_component = actor.get_component_by_class(unreal.NiagaraComponent)
        if niagara_component is None:
            return unreal_error(
                "No Niagara component found",
                f"Actor '{actor_name}' does not have a NiagaraComponent.",
            )

        # Set the float parameter
        niagara_component.set_variable_float(parameter_name, float(value))

        return unreal_success(
            f"Set float param '{parameter_name}' = {value} on '{actor_name}'",
            actor_name=actor_name,
            parameter_name=parameter_name,
            value=value,
            prompt="Reset the system with reset_niagara_system to see parameter changes from the start.",
        )

    except Exception as exc:
        return unreal_error(
            "Failed to set float parameter",
            str(exc),
            actor_name=actor_name,
            parameter_name=parameter_name,
        )
