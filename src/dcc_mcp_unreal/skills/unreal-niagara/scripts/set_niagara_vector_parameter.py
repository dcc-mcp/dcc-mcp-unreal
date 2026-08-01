"""Set a 3D vector parameter on a Niagara component."""

from __future__ import annotations

import math

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import find_level_actor, unreal_error, unreal_success


@skill_entry
def set_niagara_vector_parameter(
    actor_name: str,
    parameter_name: str,
    vector: list,
    **kwargs,
) -> dict:
    """Set a 3D vector parameter on a Niagara component.

    Args:
        actor_name: Label or name of the Niagara actor in the level.
        parameter_name: Name of the exposed vector parameter.
        vector: [X, Y, Z] vector values.

    Returns:
        ActionResultModel dict.
    """
    if not actor_name or not parameter_name or not vector:
        return unreal_error(
            "Missing required parameters",
            "actor_name, parameter_name, and vector are required",
        )
    if len(vector) != 3:
        return unreal_error(
            "Invalid vector",
            "vector must have exactly 3 components [X, Y, Z]",
        )
    vector_values = [float(component) for component in vector]
    if not all(math.isfinite(component) for component in vector_values):
        return unreal_error("Invalid vector", "all vector components must be finite numbers")

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

        vec = unreal.Vector(*vector_values)
        niagara_component.set_variable_vec3(parameter_name, vec)

        return unreal_success(
            f"Set vector param '{parameter_name}' = [{vector_values[0]:.2f}, {vector_values[1]:.2f}, {vector_values[2]:.2f}] on '{actor_name}'",
            actor_name=actor_name,
            parameter_name=parameter_name,
            vector=vector_values,
            prompt="Use reset_niagara_system to restart the effect with the new vector.",
        )

    except Exception as exc:
        return unreal_error(
            "Failed to set vector parameter",
            str(exc),
            actor_name=actor_name,
            parameter_name=parameter_name,
        )
