"""Add a camera cut track and bind camera actors for shot switching in a Level Sequence."""

from __future__ import annotations

import math

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import find_level_actor, unreal_error, unreal_from_exception, unreal_success


def _find_named_binding(sequence, binding_name: str):
    get_bindings = getattr(sequence, "get_bindings", None)
    if not callable(get_bindings):
        return None
    for binding in get_bindings() or []:
        get_display_name = getattr(binding, "get_display_name", None)
        if callable(get_display_name) and str(get_display_name()) == binding_name:
            return binding
    return None


@skill_entry
def add_camera_cut_track(
    sequence_path: str,
    camera_name: str,
    start_time: float,
    end_time: float,
    binding_name: str = "",
    **kwargs,
) -> dict:
    """Add a camera cut track and bind a camera with a time range.

    Args:
        sequence_path: Package path to the Level Sequence.
        camera_name: Name of the CineCameraActor in the level.
        start_time: Shot start time in seconds.
        end_time: Shot end time in seconds.
        binding_name: Custom name for the camera binding; defaults to camera_name.

    Returns:
        ActionResultModel dict.
    """
    if not sequence_path or not camera_name:
        return unreal_error(
            "Missing required parameters",
            "sequence_path and camera_name are required",
        )
    if not math.isfinite(start_time) or not math.isfinite(end_time) or start_time >= end_time:
        return unreal_error(
            "Invalid time range",
            "start_time and end_time must be finite, and start_time must be less than end_time",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        sequence = unreal.load_asset(sequence_path)
        if sequence is None:
            return unreal_error("Level Sequence not found", f"No asset at '{sequence_path}'.")

        # Find the camera actor in the level
        camera_actor = find_level_actor(camera_name)
        if camera_actor is None:
            return unreal_error(
                "Camera actor not found",
                f"No camera named '{camera_name}' in the current level.",
                possible_solutions=[
                    "Create a camera first with unreal_actors__spawn_actor (CineCameraActor).",
                    "Check the actor label in the World Outliner.",
                ],
            )

        resolved_binding = binding_name or camera_name

        # Get or create the camera cut track
        get_tracks = getattr(sequence, "get_tracks", None) or getattr(sequence, "get_master_tracks", None)
        if not callable(get_tracks):
            return unreal_error("Sequence track query unavailable", "This Unreal version exposes no track query API.")
        camera_cut_track = next(
            (track for track in get_tracks() if isinstance(track, unreal.MovieSceneCameraCutTrack)),
            None,
        )
        if camera_cut_track is None:
            add_track = getattr(sequence, "add_track", None) or getattr(sequence, "add_master_track", None)
            if not callable(add_track):
                return unreal_error(
                    "Sequence track authoring unavailable", "This Unreal version exposes no track add API."
                )
            camera_cut_track = add_track(unreal.MovieSceneCameraCutTrack)
        if camera_cut_track is None:
            return unreal_error("Failed to add camera cut track", "The sequence rejected the camera cut track.")

        # Reuse an existing possessable so camera cuts evaluate its transform track.
        camera_binding = _find_named_binding(sequence, resolved_binding)
        if camera_binding is None:
            camera_binding = sequence.add_possessable(camera_actor)
        if camera_binding is None:
            return unreal_error("Failed to add camera binding", f"Could not bind camera '{camera_name}'.")
        if binding_name and str(camera_binding.get_display_name()) != binding_name:
            camera_binding.set_display_name(binding_name)

        # Add camera cut section
        get_tick_resolution = getattr(sequence, "get_tick_resolution", None)
        tick_resolution = get_tick_resolution() if callable(get_tick_resolution) else None
        if tick_resolution is None:
            tick_resolution = sequence.get_display_rate()
        try:
            tick_numerator = float(tick_resolution.numerator)
            tick_denominator = float(tick_resolution.denominator)
        except (AttributeError, TypeError, ValueError):
            tick_numerator = tick_denominator = 0.0
        if tick_numerator <= 0 or tick_denominator <= 0:
            return unreal_error("Invalid sequence frame rate", "The Level Sequence has a non-positive display rate.")
        start_frame = round(start_time * tick_numerator / tick_denominator)
        end_frame = round(end_time * tick_numerator / tick_denominator)

        camera_cut_section = camera_cut_track.add_section()
        if camera_cut_section is None:
            return unreal_error("Failed to add camera cut section", "The camera cut track rejected a new section.")
        camera_cut_section.set_range(start_frame, end_frame)
        # Ask the sequence for the binding ID so it carries the correct local
        # binding space. A GUID-only struct can silently fall back to the
        # actor's level transform during MRQ renders.
        get_binding_id = getattr(sequence, "get_binding_id", None)
        if callable(get_binding_id):
            camera_cut_section.set_camera_binding_id(get_binding_id(camera_binding))
        else:
            set_camera_guid = getattr(camera_cut_section, "set_camera_guid", None)
            if callable(set_camera_guid):
                set_camera_guid(camera_binding.get_id())
                camera_binding_id = None
            else:
                camera_binding_id = unreal.MovieSceneObjectBindingID()
                camera_binding_id.set_editor_property("guid", camera_binding.get_id())
                camera_cut_section.set_camera_binding_id(camera_binding_id)

        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence):
            return unreal_error("Failed to save Level Sequence", f"Unreal could not save '{sequence_path}'.")

        return unreal_success(
            f"Added camera cut '{resolved_binding}': {start_time:.1f}s–{end_time:.1f}s",
            sequence_path=sequence_path,
            camera_name=camera_name,
            binding_name=resolved_binding,
            start_time=start_time,
            end_time=end_time,
            start_frame=start_frame,
            end_frame=end_frame,
            prompt="Add more camera cuts, then use queue_sequence_render to prepare an MRQ job.",
        )

    except Exception as exc:
        return unreal_from_exception(
            exc,
            f"Failed to add camera cut for '{camera_name}'",
            sequence_path=sequence_path,
            camera_name=camera_name,
        )
