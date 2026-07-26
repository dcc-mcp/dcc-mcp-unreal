"""Set a linear color parameter on a Niagara component."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_success


@skill_entry
def set_niagara_color_parameter(
    actor_name: str,
    parameter_name: str,
    color: list,
    **kwargs,
) -> dict:
    """Set a linear color parameter on a Niagara component.

    Args:
        actor_name: Label or name of the Niagara actor in the level.
        parameter_name: Name of the exposed color parameter.
        color: [R, G, B] or [R, G, B, A] linear values in 0-1 range.

    Returns:
        ActionResultModel dict.
    """
    if not actor_name or not parameter_name or not color:
        return unreal_error(
            "Missing required parameters",
            "actor_name, parameter_name, and color are required",
        )
    if len(color) < 3:
        return unreal_error(
            "Invalid color",
            "color must have at least 3 components [R, G, B]",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        # Find actor
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
                )
            actor = matches[0]

        niagara_component = actor.get_component_by_class(unreal.NiagaraComponent)
        if niagara_component is None:
            return unreal_error(
                "No Niagara component found",
                f"Actor '{actor_name}' does not have a NiagaraComponent.",
            )

        # Build linear color
        r = float(color[0])
        g = float(color[1])
        b = float(color[2])
        a = float(color[3]) if len(color) >= 4 else 1.0

        linear_color = unreal.LinearColor(r, g, b, a)
        niagara_component.set_variable_linear_color(parameter_name, linear_color)

        return unreal_success(
            f"Set color param '{parameter_name}' = [{r:.2f}, {g:.2f}, {b:.2f}, {a:.2f}] on '{actor_name}'",
            actor_name=actor_name,
            parameter_name=parameter_name,
            color=[r, g, b, a],
            prompt="Reset the system with reset_niagara_system to see the color change from the start.",
        )

    except Exception as exc:
        return unreal_error(
            "Failed to set color parameter",
            str(exc),
            actor_name=actor_name,
            parameter_name=parameter_name,
        )
