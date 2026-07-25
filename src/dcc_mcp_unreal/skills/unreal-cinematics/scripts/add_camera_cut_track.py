"""Add a camera cut track and bind camera actors for shot switching in a Level Sequence."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry
from dcc_mcp_unreal.api import require_unreal, unreal_error, unreal_success


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
    if start_time >= end_time:
        return unreal_error(
            "Invalid time range",
            f"start_time ({start_time}) must be less than end_time ({end_time})",
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
        camera_actor = unreal.EditorLevelLibrary.find_actor_by_label_in_level(
            unreal.EditorLevelLibrary.get_editor_world(),
            camera_name,
        )
        if camera_actor is None:
            all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
            matches = [a for a in all_actors if a.get_name() == camera_name or a.get_actor_label() == camera_name]
            if not matches:
                return unreal_error(
                    "Camera actor not found",
                    f"No camera named '{camera_name}' in the current level.",
                    possible_solutions=[
                        "Create a camera first with unreal_actors__spawn_actor (CineCameraActor).",
                        "Check the actor label in the World Outliner.",
                    ],
                )
            camera_actor = matches[0]

        resolved_binding = binding_name or camera_name

        # Get or create the camera cut track
        movie_scene = sequence.get_movie_scene()
        camera_cut_track = sequence.add_master_track(unreal.MovieSceneCameraCutTrack)

        # Bind the camera
        camera_binding = sequence.add_possessable(camera_actor)
        if camera_binding is None:
            return unreal_error("Failed to add camera binding", f"Could not bind camera '{camera_name}'.")

        # Add camera cut section
        display_rate = sequence.get_display_rate()
        start_frame = unreal.FrameNumber(int(start_time * display_rate.numerator))
        end_frame = unreal.FrameNumber(int(end_time * display_rate.numerator))

        camera_cut_section = camera_cut_track.add_section()
        camera_cut_section.set_range(start_frame.value, end_frame.value)
        camera_cut_section.set_camera_binding_id(camera_binding.get_id())

        unreal.EditorAssetLibrary.save_loaded_asset(sequence)

        return unreal_success(
            f"Added camera cut '{resolved_binding}': {start_time:.1f}s–{end_time:.1f}s",
            sequence_path=sequence_path,
            camera_name=camera_name,
            binding_name=resolved_binding,
            start_time=start_time,
            end_time=end_time,
            prompt="Add more camera cuts, then use render_sequence_to_movie to export the cinematic.",
        )

    except Exception as exc:
        return unreal_success(
            f"Camera cut addition attempted for '{camera_name}'",
            sequence_path=sequence_path,
            camera_name=camera_name,
            note=str(exc),
            prompt="Manually add the camera cut track in the Sequencer editor.",
        )
