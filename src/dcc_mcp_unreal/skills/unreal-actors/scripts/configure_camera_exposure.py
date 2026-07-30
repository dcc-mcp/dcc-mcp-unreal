"""Lock a level camera to a deterministic manual exposure."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.api import find_level_actor


@skill_entry
def configure_camera_exposure(
    actor_name: str = "",
    exposure_compensation: float = 0.0,
    **kwargs,
) -> dict:
    """Disable eye adaptation and apply a fixed exposure compensation."""
    import unreal  # noqa: PLC0415

    if not actor_name:
        return skill_error("actor_name is required", "No camera actor name was provided")
    if not -16 <= exposure_compensation <= 16:
        return skill_error("Invalid exposure compensation", "Expected a value in the -16..16 EV range")

    actor = find_level_actor(actor_name)
    if actor is None:
        return skill_error(
            f"Actor not found: '{actor_name}'",
            "No matching actor exists in the current level",
            prompt="Use list_actors to retrieve the exact camera actor name.",
        )
    component = actor.get_component_by_class(unreal.CameraComponent)
    if component is None:
        return skill_error(f"Actor is not a camera: '{actor_name}'", "The actor has no CameraComponent")

    try:
        settings = component.get_editor_property("post_process_settings")
        settings.set_editor_property("override_auto_exposure_method", True)
        settings.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
        settings.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
        settings.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
        settings.set_editor_property("override_auto_exposure_bias", True)
        settings.set_editor_property("auto_exposure_bias", float(exposure_compensation))
        component.set_editor_property("post_process_settings", settings)
    except Exception as exc:
        return skill_error(f"Unable to configure camera exposure for '{actor_name}'", str(exc))

    return skill_success(
        f"Locked manual exposure on camera '{actor_name}'",
        prompt="Use save_level to persist the camera settings.",
        actor_name=actor_name,
        exposure_method="manual",
        apply_physical_camera_exposure=False,
        exposure_compensation=float(exposure_compensation),
    )


def main(**kwargs) -> dict:
    return configure_camera_exposure(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
