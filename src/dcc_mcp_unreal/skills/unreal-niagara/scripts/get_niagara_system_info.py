"""Inspect a Niagara system: emitters, parameters, and state."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_success


@skill_entry
def get_niagara_system_info(
    target: str,
    **kwargs,
) -> dict:
    """Inspect a Niagara system asset or running actor.

    Args:
        target: Either a Niagara system asset path (/Game/VFX/MySystem)
                or an actor label for a spawned Niagara actor.

    Returns:
        ActionResultModel dict with emitter and parameter info.
    """
    if not target:
        return unreal_error(
            "target is required",
            "Provide a Niagara system path or actor name.",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        # Determine if target is an asset path or an actor
        niagara_component = None
        system_asset = None
        actor_name = ""
        is_actor = False

        if target.startswith("/Game") or target.startswith("/Niagara"):
            # Try as asset path
            system_asset = unreal.load_asset(target)
            if system_asset is not None and isinstance(system_asset, unreal.NiagaraSystem):
                pass  # We have the asset
            elif system_asset is not None:
                return unreal_error(
                    "Asset is not a Niagara system",
                    f"'{target}' is a {type(system_asset).__name__}.",
                )
        else:
            # Try as actor name
            actor = unreal.EditorLevelLibrary.find_actor_by_label_in_level(
                unreal.EditorLevelLibrary.get_editor_world(),
                target,
            )
            if actor is None:
                all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
                matches = [a for a in all_actors if a.get_name() == target or a.get_actor_label() == target]
                if matches:
                    actor = matches[0]

            if actor is not None:
                niagara_component = actor.get_component_by_class(unreal.NiagaraComponent)
                if niagara_component is not None:
                    is_actor = True
                    actor_name = target
                    system_asset = niagara_component.get_asset()

        if system_asset is None:
            return unreal_error(
                "Niagara system not found",
                f"Could not resolve '{target}' to a Niagara system or actor.",
                possible_solutions=[
                    "Use /Game/VFX/SystemName for an asset path.",
                    "Use the actor label for a spawned Niagara actor.",
                ],
            )

        # Gather emitter info
        emitters = system_asset.get_emitter_handles()
        emitter_info = []
        for i, emitter_handle in enumerate(emitters):
            emitter_instance = emitter_handle.get_instance()
            emitter_name = emitter_instance.get_name() if emitter_instance else f"emitter_{i}"

            emitter_entry = {
                "name": emitter_name,
                "index": i,
                "is_enabled": emitter_handle.get_is_enabled() if hasattr(emitter_handle, "get_is_enabled") else True,
            }

            # Try to get modules
            if emitter_instance is not None and hasattr(emitter_instance, "get_scripts"):
                scripts = emitter_instance.get_scripts()
                module_names = []
                for script in scripts:
                    if hasattr(script, "get_name"):
                        module_names.append(script.get_name())
                emitter_entry["modules"] = module_names

            emitter_info.append(emitter_entry)

        # Gather exposed parameters
        exposed_params = []
        if hasattr(system_asset, "get_exposed_parameters"):
            exposed = system_asset.get_exposed_parameters()
            if exposed is not None:
                for param in exposed:
                    param_info = {
                        "name": param.get_name() if hasattr(param, "get_name") else str(param),
                    }
                    if hasattr(param, "get_type"):
                        param_info["type"] = str(param.get_type())
                    exposed_params.append(param_info)

        system_name = system_asset.get_name() if system_asset else "unknown"

        context = {
            "system_name": system_name,
            "system_path": target if target.startswith("/Game") else str(system_asset.get_path_name()),
            "emitter_count": len(emitter_info),
            "emitters": emitter_info,
            "exposed_parameter_count": len(exposed_params),
            "exposed_parameters": exposed_params,
            "is_running_in_level": is_actor,
        }
        if is_actor:
            context["actor_name"] = actor_name
            if niagara_component is not None:
                context["is_active"] = niagara_component.is_active()
                context["is_paused"] = (
                    niagara_component.is_paused() if hasattr(niagara_component, "is_paused") else False
                )

        return unreal_success(
            f"Niagara system '{system_name}': {len(emitter_info)} emitters, {len(exposed_params)} params",
            **context,
            prompt="Use set_niagara_float_parameter or set_niagara_emitter_state to modify.",
        )

    except Exception as exc:
        return unreal_error(
            "Failed to inspect Niagara system",
            str(exc),
            target=target,
        )
