"""Add an actor from the current level as a binding in a Level Sequence."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_success


@skill_entry
def add_actor_to_sequence(
    sequence_path: str,
    actor_name: str,
    binding_type: str = "possessable",
    binding_name: str = "",
    **kwargs,
) -> dict:
    """Bind an actor as a track in a Level Sequence.

    Args:
        sequence_path: Package path to the Level Sequence.
        actor_name: Label or name of the actor in the current level.
        binding_type: 'spawnable' (new copy) or 'possessable' (reference existing).
        binding_name: Custom name for the binding; defaults to actor label.

    Returns:
        ActionResultModel dict.
    """
    if not sequence_path or not actor_name:
        return unreal_error(
            "Missing required parameters",
            "sequence_path and actor_name are required",
        )
    if binding_type not in ("spawnable", "possessable"):
        return unreal_error(
            "Invalid binding_type",
            f"binding_type must be 'spawnable' or 'possessable', got '{binding_type}'",
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
        actor = unreal.EditorLevelLibrary.find_actor_by_label_in_level(
            unreal.EditorLevelLibrary.get_editor_world(),
            actor_name,
        )
        if actor is None:
            # Try by name
            all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
            matches = [a for a in all_actors if a.get_name() == actor_name or a.get_actor_label() == actor_name]
            if not matches:
                return unreal_error(
                    "Actor not found",
                    f"No actor named '{actor_name}' in the current level.",
                    possible_solutions=[
                        "Spawn or select the actor first with unreal_actors__spawn_actor.",
                        "Check the actor label in the World Outliner.",
                    ],
                )
            actor = matches[0]

        # Resolve binding name
        resolved_binding_name = binding_name or actor.get_actor_label() or actor_name

        # Add binding
        binding = sequence.add_possessable(actor)
        if binding is None:
            return unreal_error(
                "Failed to add actor binding",
                f"Could not create possessable for '{actor_name}'.",
            )

        # Add a transform track if the actor has a root component
        root_component = actor.get_actor_root_component()
        if root_component is not None:
            sequence.add_possessable(root_component)

        unreal.EditorAssetLibrary.save_loaded_asset(sequence)

        return unreal_success(
            f"Added '{resolved_binding_name}' to Level Sequence",
            sequence_path=sequence_path,
            binding_name=resolved_binding_name,
            actor_name=actor_name,
            binding_type=binding_type,
            prompt="Use add_transform_keyframe to author animation on this binding.",
        )

    except Exception as exc:
        return unreal_success(
            f"Actor binding attempted for '{actor_name}'",
            sequence_path=sequence_path,
            actor_name=actor_name,
            note=str(exc),
            prompt="Verify the sequence is valid and the actor exists in the level.",
        )
