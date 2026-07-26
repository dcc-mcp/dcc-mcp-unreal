"""Inspect a Niagara system: emitters, parameters, and state."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import find_level_actor, unreal_error, unreal_success


@skill_entry
def get_niagara_system_info(
    target: str,
    **kwargs,
) -> dict:
    """Resolve a Niagara system asset or running actor and report basic state.

    Args:
        target: Either a Niagara system asset path (/Game/VFX/MySystem)
                or an actor label for a spawned Niagara actor.

    Returns:
        ActionResultModel dict with verified asset/component state.
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
            actor = find_level_actor(target)

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

        system_name = system_asset.get_name() if system_asset else "unknown"
        system_path = str(system_asset.get_path_name())

        context = {
            "system_name": system_name,
            "system_path": system_path,
            "is_running_in_level": is_actor,
            "emitter_details_available": False,
            "parameter_details_available": False,
        }
        if is_actor:
            context["actor_name"] = actor_name
            if niagara_component is not None:
                context["is_active"] = niagara_component.is_active()
                context["is_paused"] = (
                    niagara_component.is_paused() if hasattr(niagara_component, "is_paused") else False
                )

        return unreal_success(
            f"Resolved Niagara system '{system_name}'",
            **context,
            prompt=(
                "Use the Niagara editor or UE 5.8 official Niagara toolsets for emitter/module inspection; "
                "the standard Unreal Python API does not expose those details."
            ),
        )

    except Exception as exc:
        return unreal_error(
            "Failed to inspect Niagara system",
            str(exc),
            target=target,
        )
