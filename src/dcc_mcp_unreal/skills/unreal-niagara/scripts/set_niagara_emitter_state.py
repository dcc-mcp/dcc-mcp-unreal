"""Enable or disable a specific emitter within a Niagara system component."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_success


@skill_entry
def set_niagara_emitter_state(
    actor_name: str,
    emitter_name: str,
    enabled: bool,
    **kwargs,
) -> dict:
    """Enable or disable a specific emitter in a Niagara system.

    Args:
        actor_name: Label or name of the Niagara actor in the level.
        emitter_name: Name of the emitter to toggle.
        enabled: True to enable, False to disable.

    Returns:
        ActionResultModel dict.
    """
    if not actor_name or not emitter_name:
        return unreal_error(
            "Missing required parameters",
            "actor_name and emitter_name are required",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
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

        # Get the system asset for emitter handles
        system_asset = niagara_component.get_asset()
        if system_asset is None:
            return unreal_error(
                "No system asset",
                f"Actor '{actor_name}' has no Niagara system asset.",
            )

        # Find and toggle the emitter
        emitter_handles = system_asset.get_emitter_handles()
        found = False
        for handle in emitter_handles:
            instance = handle.get_instance()
            if instance is not None and instance.get_name() == emitter_name:
                handle.set_enabled(enabled)
                found = True
                break

        if not found:
            return unreal_error(
                "Emitter not found",
                f"No emitter named '{emitter_name}' in the system.",
                possible_solutions=[
                    "Use get_niagara_system_info to list available emitters.",
                ],
            )

        # Reset the component to apply the change
        niagara_component.deactivate()
        niagara_component.activate(reset=True)

        state = "enabled" if enabled else "disabled"
        return unreal_success(
            f"Emitter '{emitter_name}' {state} on '{actor_name}'",
            actor_name=actor_name,
            emitter_name=emitter_name,
            enabled=enabled,
            prompt="The Niagara system has been reset to apply the emitter state change.",
        )

    except Exception as exc:
        return unreal_error(
            "Failed to toggle emitter state",
            str(exc),
            actor_name=actor_name,
            emitter_name=emitter_name,
        )
