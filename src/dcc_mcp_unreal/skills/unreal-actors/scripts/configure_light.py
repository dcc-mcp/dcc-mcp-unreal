"""Configure common properties on an existing Unreal light actor."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.api import find_level_actor


@skill_entry
def configure_light(
    actor_name: str = "",
    intensity: float = -1.0,
    color_r: float = -1.0,
    color_g: float = -1.0,
    color_b: float = -1.0,
    temperature_kelvin: float = 0.0,
    attenuation_radius: float = -1.0,
    source_radius: float = -1.0,
    soft_source_radius: float = -1.0,
    **kwargs,
) -> dict:
    """Set an allowlisted subset of physically useful light properties."""
    import unreal  # noqa: PLC0415

    if not actor_name:
        return skill_error("actor_name is required", "No light actor name was provided")
    if intensity < -1 or temperature_kelvin < 0 or min(attenuation_radius, source_radius, soft_source_radius) < -1:
        return skill_error("Invalid light value", "Numeric light controls must be non-negative or -1 for unchanged")
    color_values = (color_r, color_g, color_b)
    if any(value >= 0 for value in color_values) and not all(0 <= value <= 1 for value in color_values):
        return skill_error("Invalid light color", "Set all RGB values together in the 0..1 range")

    actor = find_level_actor(actor_name)
    if actor is None:
        return skill_error(
            f"Actor not found: '{actor_name}'",
            "No matching actor exists in the current level",
            prompt="Use list_actors to retrieve the exact light actor name.",
        )
    component = actor.get_component_by_class(unreal.LightComponentBase)
    if component is None:
        return skill_error(f"Actor is not a light: '{actor_name}'", "The actor has no LightComponentBase")

    applied = {}
    try:
        if intensity >= 0:
            component.set_editor_property("intensity", float(intensity))
            applied["intensity"] = float(intensity)
        if all(value >= 0 for value in color_values):
            light_color = unreal.Color(
                r=round(color_r * 255),
                g=round(color_g * 255),
                b=round(color_b * 255),
                a=255,
            )
            component.set_editor_property("light_color", light_color)
            applied["color"] = [float(color_r), float(color_g), float(color_b)]
        if temperature_kelvin > 0:
            component.set_editor_property("temperature", float(temperature_kelvin))
            component.set_editor_property("use_temperature", True)
            applied["temperature_kelvin"] = float(temperature_kelvin)
        for property_name, value in (
            ("attenuation_radius", attenuation_radius),
            ("source_radius", source_radius),
            ("soft_source_radius", soft_source_radius),
        ):
            if value >= 0:
                component.set_editor_property(property_name, float(value))
                applied[property_name] = float(value)
    except Exception as exc:
        return skill_error(f"Unsupported light property for '{actor_name}'", str(exc))

    return skill_success(
        f"Configured light '{actor_name}'",
        prompt="Use save_level to persist the light settings.",
        actor_name=actor_name,
        light_class=type(component).__name__,
        applied=applied,
    )


def main(**kwargs) -> dict:
    return configure_light(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
