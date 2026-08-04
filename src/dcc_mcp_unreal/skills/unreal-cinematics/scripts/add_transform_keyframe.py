"""Add a transform keyframe for a bound actor at a specific time in a Level Sequence."""

from __future__ import annotations

import math
from typing import Optional

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success


@skill_entry
def add_transform_keyframe(
    sequence_path: str,
    binding_name: str,
    time: float,
    location: Optional[list] = None,
    rotation: Optional[list] = None,
    scale: Optional[list] = None,
    interpolation: str = "default",
    **kwargs,
) -> dict:
    """Add a transform keyframe for a bound actor.

    Args:
        sequence_path: Package path to the Level Sequence.
        binding_name: Name of the actor binding in the sequence.
        time: Time in seconds for the keyframe.
        location: [x, y, z] world location in Unreal units (cm).
        rotation: [pitch, yaw, roll] rotation in degrees.
        scale: [x, y, z] scale factor.
        interpolation: Optional key interpolation mode: default, linear, or constant.

    Returns:
        ActionResultModel dict.
    """
    if not sequence_path or not binding_name:
        return unreal_error(
            "Missing required parameters",
            "sequence_path and binding_name are required",
        )
    if location is None and rotation is None and scale is None:
        return unreal_error(
            "No transform data provided",
            "At least one of location, rotation, or scale must be specified.",
        )
    if not math.isfinite(time):
        return unreal_error("Invalid key time", "time must be a finite number")
    if interpolation not in {"default", "linear", "constant"}:
        return unreal_error(
            "Invalid interpolation",
            "interpolation must be one of: default, linear, constant",
        )
    for field_name, values in (("location", location), ("rotation", rotation), ("scale", scale)):
        if values is None:
            continue
        if len(values) != 3 or not all(math.isfinite(float(value)) for value in values):
            return unreal_error(
                f"Invalid {field_name}",
                f"{field_name} must contain exactly three finite numbers",
            )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        sequence = unreal.load_asset(sequence_path)
        if sequence is None:
            return unreal_error("Level Sequence not found", f"No asset at '{sequence_path}'.")

        # Find the binding
        bindings = sequence.get_bindings()
        target_binding = None
        for b in bindings:
            if b.get_display_name() == binding_name:
                target_binding = b
                break

        if target_binding is None:
            return unreal_error(
                "Binding not found",
                f"No binding named '{binding_name}' in sequence '{sequence_path}'.",
                possible_solutions=["Use get_sequence_info to list available bindings."],
            )

        # Get or create transform tracks
        tracks = target_binding.get_tracks()
        transform_section = None
        for track in tracks:
            if isinstance(track, unreal.MovieScene3DTransformTrack):
                sections = track.get_sections()
                if sections:
                    transform_section = sections[0]
                break

        if transform_section is None:
            return unreal_error(
                "No transform track found",
                "The binding does not have a transform track.",
            )

        # Get the channels
        channels = transform_section.get_all_channels()

        # Set keyframes
        display_rate = sequence.get_display_rate()
        if display_rate.numerator <= 0 or display_rate.denominator <= 0:
            return unreal_error("Invalid sequence frame rate", "The Level Sequence has a non-positive display rate.")
        key_time = unreal.FrameNumber(round(time * display_rate.numerator / display_rate.denominator))
        interpolation_mode = {
            "linear": unreal.RichCurveInterpMode.RCIM_LINEAR,
            "constant": unreal.RichCurveInterpMode.RCIM_CONSTANT,
        }.get(interpolation)

        def get_channel_name(channel) -> str:
            get_editor_property = getattr(channel, "get_editor_property", None)
            if callable(get_editor_property):
                try:
                    return str(get_editor_property("channel_name"))
                except Exception:
                    pass
            return str(channel.get_name())

        def add_key(channel, value: float) -> None:
            try:
                key = channel.add_key(key_time, value, 0.0)
            except TypeError:
                key = channel.add_key(key_time, value)
            if interpolation_mode is not None:
                key.set_interpolation_mode(interpolation_mode)

        keys_added = 0

        if location is not None:
            for channel in channels:
                channel_name = get_channel_name(channel)
                if "Location.X" in channel_name:
                    add_key(channel, float(location[0]))
                    keys_added += 1
                elif "Location.Y" in channel_name:
                    add_key(channel, float(location[1]))
                    keys_added += 1
                elif "Location.Z" in channel_name:
                    add_key(channel, float(location[2]))
                    keys_added += 1

        if rotation is not None:
            for channel in channels:
                channel_name = get_channel_name(channel)
                if "Rotation.X" in channel_name:
                    add_key(channel, float(rotation[2]))
                    keys_added += 1
                elif "Rotation.Y" in channel_name:
                    add_key(channel, float(rotation[0]))
                    keys_added += 1
                elif "Rotation.Z" in channel_name:
                    add_key(channel, float(rotation[1]))
                    keys_added += 1

        if scale is not None:
            for channel in channels:
                channel_name = get_channel_name(channel)
                if "Scale.X" in channel_name:
                    add_key(channel, float(scale[0]))
                    keys_added += 1
                elif "Scale.Y" in channel_name:
                    add_key(channel, float(scale[1]))
                    keys_added += 1
                elif "Scale.Z" in channel_name:
                    add_key(channel, float(scale[2]))
                    keys_added += 1

        if keys_added == 0:
            return unreal_error("No matching transform channels", "The transform section exposed no matching channels.")
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence):
            return unreal_error("Failed to save Level Sequence", f"Unreal could not save '{sequence_path}'.")

        return unreal_success(
            f"Added transform keyframe at t={time:.2f}s for '{binding_name}'",
            sequence_path=sequence_path,
            binding_name=binding_name,
            time=time,
            location=location,
            rotation=rotation,
            scale=scale,
            interpolation=interpolation,
            keys_added=keys_added,
            prompt="Use add_transform_keyframe again for more keyframes, then queue_sequence_render.",
        )

    except Exception as exc:
        return unreal_from_exception(
            exc,
            f"Failed to add a keyframe for '{binding_name}'",
            sequence_path=sequence_path,
            binding_name=binding_name,
            time=time,
            possible_solutions=[
                "Check that the binding has a transform track.",
                "Use get_sequence_info to inspect the sequence bindings and tracks.",
            ],
        )
