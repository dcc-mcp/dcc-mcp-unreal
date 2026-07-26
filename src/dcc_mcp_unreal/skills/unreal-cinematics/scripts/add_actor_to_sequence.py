"""Add an actor from the current level as a binding in a Level Sequence."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import find_level_actor, unreal_error, unreal_from_exception, unreal_success


@skill_entry
def add_actor_to_sequence(
    sequence_path: str,
    actor_name: str,
    binding_name: str = "",
    **kwargs,
) -> dict:
    """Bind an actor as a track in a Level Sequence.

    Args:
        sequence_path: Package path to the Level Sequence.
        actor_name: Label or name of the actor in the current level.
        binding_name: Custom name for the binding; defaults to actor label.

    Returns:
        ActionResultModel dict.
    """
    if not sequence_path or not actor_name:
        return unreal_error(
            "Missing required parameters",
            "sequence_path and actor_name are required",
        )
    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        sequence = unreal.load_asset(sequence_path)
        if sequence is None:
            return unreal_error(
                "Level Sequence not found",
                f"No asset at '{sequence_path}'.",
            )

        # Find the actor in the current level
        actor = find_level_actor(actor_name)
        if actor is None:
            return unreal_error(
                "Actor not found",
                f"No actor named '{actor_name}' in the current level.",
                possible_solutions=[
                    "Spawn or select the actor first with unreal_actors__spawn_actor.",
                    "Check the actor label in the World Outliner.",
                ],
            )

        # Resolve binding name
        resolved_binding_name = binding_name or actor.get_actor_label() or actor_name

        # Add binding
        binding = sequence.add_possessable(actor)
        if binding is None:
            return unreal_error(
                "Failed to add actor binding",
                f"Could not create possessable for '{actor_name}'.",
            )
        if binding_name:
            binding.set_display_name(binding_name)

        transform_track = binding.add_track(unreal.MovieScene3DTransformTrack)
        if transform_track is None:
            return unreal_error("Failed to add transform track", f"Could not add a transform track for '{actor_name}'.")
        transform_section = transform_track.add_section()
        if transform_section is None:
            return unreal_error(
                "Failed to add transform section", f"Could not add a transform section for '{actor_name}'."
            )
        transform_section.set_range(sequence.get_playback_start(), sequence.get_playback_end())

        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence):
            return unreal_error("Failed to save Level Sequence", f"Unreal could not save '{sequence_path}'.")

        return unreal_success(
            f"Added '{resolved_binding_name}' to Level Sequence",
            sequence_path=sequence_path,
            binding_name=resolved_binding_name,
            actor_name=actor_name,
            binding_type="possessable",
            prompt="Use add_transform_keyframe to author animation on this binding.",
        )

    except Exception as exc:
        return unreal_from_exception(
            exc,
            f"Failed to bind actor '{actor_name}'",
            sequence_path=sequence_path,
            actor_name=actor_name,
        )
