"""Configure an existing Sky Light actor with a specified HDR cubemap."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.api import find_level_actor


@skill_entry
def configure_sky_light(
    actor_name: str = "",
    cubemap_path: str = "",
    intensity_scale: float = 1.0,
    source_cubemap_angle: float = 0.0,
    **kwargs,
) -> dict:
    """Use a TextureCube as the lighting source for one level Sky Light."""
    import unreal  # noqa: PLC0415

    if not actor_name:
        return skill_error("actor_name is required", "No Sky Light actor name was provided")
    if not cubemap_path:
        return skill_error("cubemap_path is required", "No TextureCube asset path was provided")
    if intensity_scale < 0:
        return skill_error("intensity_scale must be non-negative", str(intensity_scale))

    actor = find_level_actor(actor_name)
    if actor is None:
        return skill_error(
            f"Actor not found: '{actor_name}'",
            "No matching actor exists in the current level",
            prompt="Use list_actors to retrieve the exact Sky Light name or label.",
        )

    component = actor.get_component_by_class(unreal.SkyLightComponent)
    if component is None:
        return skill_error(
            f"Actor is not a Sky Light: '{actor_name}'",
            "The actor has no SkyLightComponent",
        )

    cubemap = unreal.EditorAssetLibrary.load_asset(cubemap_path)
    if not isinstance(cubemap, unreal.TextureCube):
        return skill_error(
            f"TextureCube not found: {cubemap_path}",
            "cubemap_path must identify an imported HDR TextureCube asset",
        )

    angle = float(source_cubemap_angle) % 360.0
    component.set_editor_property(
        "source_type",
        unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP,
    )
    component.set_editor_property("cubemap", cubemap)
    component.set_editor_property("intensity", float(intensity_scale))
    component.set_editor_property("source_cubemap_angle", angle)
    component.set_editor_property("real_time_capture", False)

    return skill_success(
        f"Configured Sky Light '{actor_name}' with '{cubemap_path}'",
        prompt="Use save_level to persist the HDR lighting setup.",
        actor_name=actor_name,
        cubemap_path=cubemap_path,
        intensity_scale=float(intensity_scale),
        source_cubemap_angle=angle,
        source_type="specified_cubemap",
    )
