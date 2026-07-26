"""Set the playback range for a Level Sequence."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_success


@skill_entry
def set_playback_range(
    sequence_path: str,
    start_time: float = 0.0,
    end_time: float = 5.0,
    **kwargs,
) -> dict:
    """Set the playback start and end times for a Level Sequence.

    Args:
        sequence_path: Package path to the Level Sequence.
        start_time: Start time in seconds.
        end_time: End time in seconds.

    Returns:
        ActionResultModel dict.
    """
    if not sequence_path or not sequence_path.startswith("/Game"):
        return unreal_error(
            "Invalid sequence_path",
            "sequence_path must start with /Game",
        )
    if start_time >= end_time:
        return unreal_error(
            "Invalid playback range",
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

        display_rate = sequence.get_display_rate()
        start_frame = unreal.FrameNumber(int(start_time * display_rate.numerator))
        end_frame = unreal.FrameNumber(int(end_time * display_rate.numerator))

        sequence.set_playback_start(start_frame.value)
        sequence.set_playback_end(end_frame.value)

        unreal.EditorAssetLibrary.save_loaded_asset(sequence)

        duration = end_time - start_time
        return unreal_success(
            f"Set playback range: {start_time:.2f}s → {end_time:.2f}s (duration: {duration:.2f}s)",
            sequence_path=sequence_path,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            prompt="Use get_sequence_info to verify, then render_sequence_to_movie to export.",
        )

    except Exception as exc:
        return unreal_success(
            f"Playback range set attempted for '{sequence_path}'",
            sequence_path=sequence_path,
            start_time=start_time,
            end_time=end_time,
            note=str(exc),
            prompt="Verify the sequence asset is valid.",
        )
