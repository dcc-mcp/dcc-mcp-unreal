"""Set the playback range for a Level Sequence."""

from __future__ import annotations

import math

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success


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
    if not math.isfinite(start_time) or not math.isfinite(end_time) or start_time >= end_time:
        return unreal_error(
            "Invalid playback range",
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

        display_rate = sequence.get_display_rate()
        if display_rate.numerator <= 0 or display_rate.denominator <= 0:
            return unreal_error("Invalid sequence frame rate", "The Level Sequence has a non-positive display rate.")
        start_frame = round(start_time * display_rate.numerator / display_rate.denominator)
        end_frame = round(end_time * display_rate.numerator / display_rate.denominator)

        sequence.set_playback_start(start_frame)
        sequence.set_playback_end(end_frame)

        if sequence.get_playback_start() != start_frame or sequence.get_playback_end() != end_frame:
            return unreal_error(
                "Playback range verification failed", "The sequence did not retain the requested frame range."
            )
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence):
            return unreal_error("Failed to save Level Sequence", f"Unreal could not save '{sequence_path}'.")

        duration = end_time - start_time
        return unreal_success(
            f"Set playback range: {start_time:.2f}s → {end_time:.2f}s (duration: {duration:.2f}s)",
            sequence_path=sequence_path,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            start_frame=start_frame,
            end_frame=end_frame,
            prompt="Use get_sequence_info to verify, then queue_sequence_render when the sequence is ready.",
        )

    except Exception as exc:
        return unreal_from_exception(
            exc,
            f"Failed to set playback range for '{sequence_path}'",
            sequence_path=sequence_path,
            start_time=start_time,
            end_time=end_time,
        )
