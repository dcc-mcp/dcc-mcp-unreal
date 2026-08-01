"""Return detailed information about a Level Sequence."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_success


@skill_entry
def get_sequence_info(
    sequence_path: str,
    **kwargs,
) -> dict:
    """Inspect a Level Sequence: playback range, tracks, bindings, and camera cuts.

    Args:
        sequence_path: Package path to the Level Sequence.

    Returns:
        ActionResultModel dict with sequence metadata.
    """
    if not sequence_path or not sequence_path.startswith("/Game"):
        return unreal_error(
            "Invalid sequence_path",
            "sequence_path must start with /Game",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        sequence = unreal.load_asset(sequence_path)
        if sequence is None:
            return unreal_error("Level Sequence not found", f"No asset at '{sequence_path}'.")

        display_rate = sequence.get_display_rate()
        if display_rate.numerator <= 0 or display_rate.denominator <= 0:
            return unreal_error("Invalid sequence frame rate", "The Level Sequence has a non-positive display rate.")
        fps = float(display_rate.numerator) / float(display_rate.denominator)

        playback_start = sequence.get_playback_start()
        playback_end = sequence.get_playback_end()
        start_time = float(playback_start) * display_rate.denominator / display_rate.numerator
        end_time = float(playback_end) * display_rate.denominator / display_rate.numerator

        # Gather bindings
        bindings = sequence.get_bindings()
        bindings_info = []
        for b in bindings:
            binding_entry = {
                "name": str(b.get_display_name()),
                "id": str(b.get_id()),
            }
            tracks = b.get_tracks()
            track_names = [str(t.get_display_name()) for t in tracks if hasattr(t, "get_display_name")]
            binding_entry["tracks"] = track_names
            bindings_info.append(binding_entry)

        # Gather all tracks
        get_tracks = getattr(sequence, "get_tracks", None) or getattr(sequence, "get_master_tracks", None)
        if not callable(get_tracks):
            return unreal_error(
                "Sequence track inspection unavailable", "This Unreal version exposes no track query API."
            )
        all_tracks = get_tracks()
        master_track_names = [str(t.get_display_name()) for t in all_tracks if hasattr(t, "get_display_name")]

        # Check for camera cut track
        has_camera_cut = any(isinstance(track, unreal.MovieSceneCameraCutTrack) for track in all_tracks)

        return unreal_success(
            f"Sequence '{sequence_path}': {len(bindings_info)} bindings, {fps:.0f} fps, "
            f"{start_time:.1f}s–{end_time:.1f}s",
            sequence_path=sequence_path,
            frame_rate=fps,
            frame_rate_numerator=display_rate.numerator,
            frame_rate_denominator=display_rate.denominator,
            playback_start=start_time,
            playback_end=end_time,
            duration=end_time - start_time,
            binding_count=len(bindings_info),
            bindings=bindings_info,
            master_tracks=master_track_names,
            has_camera_cut_track=has_camera_cut,
            prompt="Use add_camera_cut_track to add shot switching, or queue_sequence_render to prepare an MRQ job.",
        )

    except Exception as exc:
        return unreal_error(
            "Failed to inspect Level Sequence",
            str(exc),
            sequence_path=sequence_path,
        )
