"""Shared Movie Render Queue configuration for the automotive film."""

from __future__ import annotations

from pathlib import Path


def configure_render_job(
    unreal,
    job,
    *,
    output_directory: Path,
    file_name_format: str,
    width: int,
    height: int,
    temporal_samples: int,
    frame_start: int | None = None,
    frame_end: int | None = None,
) -> None:
    """Apply the production render contract to one MRQ job."""
    config = job.get_configuration()
    output = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    output.set_editor_property("output_directory", unreal.DirectoryPath(str(output_directory)))
    output.set_editor_property("file_name_format", file_name_format)
    output.set_editor_property("output_resolution", unreal.IntPoint(width, height))
    output.set_editor_property("use_custom_frame_rate", True)
    output.set_editor_property("output_frame_rate", unreal.FrameRate(24, 1))
    output.set_editor_property("zero_pad_frame_numbers", 4)
    output.set_editor_property("override_existing_output", True)
    if frame_start is not None and frame_end is not None:
        output.set_editor_property("use_custom_playback_range", True)
        output.set_editor_property("custom_start_frame", int(frame_start))
        output.set_editor_property("custom_end_frame", int(frame_end))

    config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    config.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
    anti_aliasing = config.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    anti_aliasing.set_editor_property("spatial_sample_count", 1)
    anti_aliasing.set_editor_property("temporal_sample_count", temporal_samples)
    anti_aliasing.set_editor_property("override_anti_aliasing", True)
    anti_aliasing.set_editor_property("anti_aliasing_method", unreal.AntiAliasingMethod.AAM_TSR)
    game_override = config.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    game_override.set_editor_property("cinematic_quality_settings", True)
    game_override.set_editor_property(
        "texture_streaming",
        unreal.MoviePipelineTextureStreamingMethod.DISABLED,
    )


def apply_cinematic_console_settings(unreal) -> None:
    """Apply deterministic high-quality settings shared by previews and final output."""
    for command in (
        "r.MotionBlurQuality 4",
        "r.DepthOfFieldQuality 4",
        "r.VolumetricFog 1",
        "r.Lumen.Reflections.Quality 4",
        "r.Lumen.ScreenProbeGather.Quality 4",
    ):
        unreal.SystemLibrary.execute_console_command(None, command)
