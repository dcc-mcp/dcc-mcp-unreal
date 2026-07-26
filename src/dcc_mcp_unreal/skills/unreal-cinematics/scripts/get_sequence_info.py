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
        fps = float(display_rate.numerator) / float(display_rate.denominator) if display_rate.denominator > 0 else 0.0

        playback_start = sequence.get_playback_start()
        playback_end = sequence.get_playback_end()
        start_time = float(playback_start) / display_rate.numerator if fps > 0 else 0.0
        end_time = float(playback_end) / display_rate.numerator if fps > 0 else 0.0

        # Gather bindings
        bindings = sequence.get_bindings()
        bindings_info = []
        for b in bindings:
            binding_entry = {
                "name": b.get_display_name(),
                "id": str(b.get_id()),
            }
            tracks = b.get_tracks()
            track_names = [t.get_display_name() for t in tracks if hasattr(t, "get_display_name")]
            binding_entry["tracks"] = track_names
            bindings_info.append(binding_entry)

        # Gather all tracks
        all_tracks = sequence.get_master_tracks()
        master_track_names = [t.get_display_name() for t in all_tracks if hasattr(t, "get_display_name")]

        # Check for camera cut track
        has_camera_cut = any("CameraCut" in name for name in master_track_names)

        return unreal_success(
            f"Sequence '{sequence_path}': {len(bindings_info)} bindings, {fps:.0f} fps, "
            f"{start_time:.1f}s–{end_time:.1f}s",
            sequence_path=sequence_path,
            frame_rate=fps,
            playback_start=start_time,
            playback_end=end_time,
            duration=end_time - start_time,
            binding_count=len(bindings_info),
            bindings=bindings_info,
            master_tracks=master_track_names,
            has_camera_cut_track=has_camera_cut,
            prompt="Use add_camera_cut_track to add shot switching, or render_sequence_to_movie to export.",
        )

    except Exception as exc:
        return unreal_error(
            "Failed to inspect Level Sequence",
            str(exc),
            sequence_path=sequence_path,
        )
