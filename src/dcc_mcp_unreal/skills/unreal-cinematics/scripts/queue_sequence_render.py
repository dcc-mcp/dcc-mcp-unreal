"""Add a Level Sequence job to Unreal's active Movie Render Queue."""

from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path, PurePosixPath, PureWindowsPath

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success

_OUTPUT_CLASSES = {
    "png": "MoviePipelineImageSequenceOutput_PNG",
    "jpg": "MoviePipelineImageSequenceOutput_JPG",
    "jpeg": "MoviePipelineImageSequenceOutput_JPG",
    "exr": "MoviePipelineImageSequenceOutput_EXR",
}


def _is_absolute_output_path(value: str) -> bool:
    """Accept explicit Windows or POSIX absolute paths on every agent platform."""
    return PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()


@skill_entry
def queue_sequence_render(
    sequence_path: str,
    output_path: str,
    resolution_x: int = 1920,
    resolution_y: int = 1080,
    output_format: str = "png",
    frame_rate_override: float = 0.0,
    spatial_samples: int = 1,
    temporal_samples: int = 8,
    ocio_config_path: str = "",
    ocio_source_color_space: str = "ACEScg",
    ocio_display: str = "Rec.1886 Rec.709 - Display",
    ocio_view: str = "ACES 1.0 - SDR Video",
    **kwargs,
) -> dict:
    """Configure an active MRQ job without starting a render."""
    if not sequence_path or not sequence_path.startswith("/Game/"):
        return unreal_error("Invalid sequence_path", "sequence_path must start with /Game/")
    if not output_path or not _is_absolute_output_path(output_path):
        return unreal_error("Invalid output_path", "output_path must be an absolute output directory")
    if resolution_x <= 0 or resolution_y <= 0:
        return unreal_error("Invalid resolution", "resolution_x and resolution_y must be greater than zero")
    if not math.isfinite(frame_rate_override) or frame_rate_override < 0:
        return unreal_error("Invalid frame_rate_override", "frame_rate_override must be finite and non-negative")
    if not 1 <= spatial_samples <= 64 or not 1 <= temporal_samples <= 64:
        return unreal_error("Invalid sample count", "spatial_samples and temporal_samples must be between 1 and 64")
    ocio_path = None
    if ocio_config_path:
        ocio_path = Path(ocio_config_path).expanduser()
        if (
            not ocio_path.is_absolute()
            or not ocio_path.is_file()
            or ocio_path.suffix.lower()
            not in {
                ".ocio",
                ".ocioz",
            }
        ):
            return unreal_error(
                "Invalid OCIO config",
                "ocio_config_path must be an existing absolute .ocio or .ocioz file",
            )
        if not all(
            isinstance(value, str) and value.strip() for value in (ocio_source_color_space, ocio_display, ocio_view)
        ):
            return unreal_error(
                "Invalid OCIO transform",
                "ocio_source_color_space, ocio_display, and ocio_view must be non-empty",
            )

    normalized_format = output_format.lower()
    if normalized_format not in _OUTPUT_CLASSES:
        return unreal_error(
            "Invalid output format",
            "output_format must be one of: exr, jpg, jpeg, png. "
            "Video output requires a separately configured command-line encoder and is not supported by this tool.",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    render_queue = None
    job = None
    try:
        sequence = unreal.load_asset(sequence_path)
        if sequence is None:
            return unreal_error("Level Sequence not found", f"No asset at '{sequence_path}'.")
        if not isinstance(sequence, unreal.LevelSequence):
            return unreal_error(
                "Asset is not a Level Sequence",
                f"'{sequence_path}' is a {type(sequence).__name__}, expected LevelSequence.",
            )

        queue_subsystem_class = getattr(unreal, "MoviePipelineQueueSubsystem", None)
        if queue_subsystem_class is None:
            return unreal_error(
                "Movie Render Queue unavailable",
                "MoviePipelineQueueSubsystem is unavailable. Enable the Movie Render Queue plugin.",
            )
        mrq_subsystem = unreal.get_editor_subsystem(queue_subsystem_class)
        if mrq_subsystem is None:
            return unreal_error(
                "Movie Render Queue unavailable",
                "MoviePipelineQueueSubsystem could not be obtained. Enable the Movie Render Queue plugin.",
            )

        render_queue = mrq_subsystem.get_queue()
        if render_queue is None:
            return unreal_error("Render queue is null", "Could not obtain the movie render queue.")

        output_class = getattr(unreal, _OUTPUT_CLASSES[normalized_format], None)
        if output_class is None:
            return unreal_error(
                "Movie Render Queue output unavailable",
                f"{_OUTPUT_CLASSES[normalized_format]} is unavailable. Enable the required Movie Render Queue plugin.",
            )

        world = unreal.EditorLevelLibrary.get_editor_world()
        if world is None:
            return unreal_error("Editor world unavailable", "No editor world is open for the render job map.")
        map_path = str(world.get_path_name())
        map_package_path = map_path.split(".", 1)[0]
        if map_package_path.startswith(("/Temp/", "/Transient")) or not unreal.EditorAssetLibrary.does_asset_exist(
            map_package_path
        ):
            return unreal_error(
                "Current level is not saved",
                "Movie Render Queue requires the current level to be saved as an asset before a job is queued.",
                map_path=map_path,
            )

        job = render_queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
        if job is None:
            return unreal_error("Failed to allocate render job", "Job allocation returned None.")

        job.sequence = unreal.SoftObjectPath(sequence_path)
        job.map = unreal.SoftObjectPath(world.get_path_name())

        job_config = job.get_configuration()
        if job_config is None:
            render_queue.delete_job(job)
            return unreal_error("Render configuration unavailable", "Allocated job has no render configuration.")

        output_setting = job_config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
        format_setting = job_config.find_or_add_setting_by_class(output_class)
        if output_setting is None or format_setting is None:
            render_queue.delete_job(job)
            return unreal_error(
                "Failed to configure render output",
                f"Could not add {normalized_format} output settings to the render job.",
            )

        output_setting.output_resolution = unreal.IntPoint(resolution_x, resolution_y)
        output_setting.output_directory = unreal.DirectoryPath(output_path)
        output_setting.file_name_format = "{sequence_name}.{frame_number}"
        output_setting.use_custom_frame_rate = frame_rate_override > 0
        output_setting.zero_pad_frame_numbers = 4
        output_setting.override_existing_output = True

        deferred_class = getattr(unreal, "MoviePipelineDeferredPassBase", None)
        aa_class = getattr(unreal, "MoviePipelineAntiAliasingSetting", None)
        game_override_class = getattr(unreal, "MoviePipelineGameOverrideSetting", None)
        if deferred_class is None or aa_class is None or game_override_class is None:
            render_queue.delete_job(job)
            return unreal_error("High-quality MRQ settings unavailable", "Enable the Movie Render Queue plugin")
        job_config.find_or_add_setting_by_class(deferred_class)
        anti_aliasing = job_config.find_or_add_setting_by_class(aa_class)
        anti_aliasing.spatial_sample_count = spatial_samples
        anti_aliasing.temporal_sample_count = temporal_samples
        anti_aliasing.override_anti_aliasing = True
        if hasattr(unreal, "AntiAliasingMethod"):
            anti_aliasing.anti_aliasing_method = unreal.AntiAliasingMethod.AAM_TSR
        game_override = job_config.find_or_add_setting_by_class(game_override_class)
        game_override.cinematic_quality_settings = True
        if hasattr(unreal, "MoviePipelineTextureStreamingMethod"):
            game_override.texture_streaming = unreal.MoviePipelineTextureStreamingMethod.DISABLED

        if ocio_path is not None:
            ocio_types = (
                "MoviePipelineColorSetting",
                "OpenColorIOConfiguration",
                "OpenColorIOColorSpace",
                "OpenColorIODisplayView",
                "OpenColorIOColorConversionSettings",
                "OpenColorIODisplayConfiguration",
                "OpenColorIOViewTransformDirection",
                "FilePath",
            )
            missing = [name for name in ocio_types if getattr(unreal, name, None) is None]
            if missing:
                render_queue.delete_job(job)
                return unreal_error(
                    "OpenColorIO unavailable",
                    f"Enable the OpenColorIO plugin; missing Unreal types: {', '.join(missing)}",
                )
            ocio_config = unreal.OpenColorIOConfiguration(
                outer=job,
                name="DccMcpMovieRenderOCIO",
            )
            source = unreal.OpenColorIOColorSpace(
                color_space_name=ocio_source_color_space,
                family_name="",
            )
            display_view = unreal.OpenColorIODisplayView(
                display=ocio_display,
                view=ocio_view,
            )
            ocio_config.set_editor_property(
                "configuration_file",
                unreal.FilePath(file_path=str(ocio_path.resolve())),
            )
            ocio_config.set_editor_property("desired_color_spaces", [source])
            ocio_config.set_editor_property("desired_display_views", [display_view])
            ocio_config.reload_existing_colorspaces(True)
            conversion = unreal.OpenColorIOColorConversionSettings(
                configuration_source=ocio_config,
                source_color_space=source,
                destination_display_view=display_view,
                display_view_direction=unreal.OpenColorIOViewTransformDirection.FORWARD,
            )
            color_output = job_config.find_or_add_setting_by_class(unreal.MoviePipelineColorSetting)
            color_output.ocio_configuration = unreal.OpenColorIODisplayConfiguration(
                is_enabled=True,
                color_configuration=conversion,
            )
            color_output.disable_tone_curve = True

        rate = None
        if frame_rate_override > 0:
            rate = Fraction(str(frame_rate_override)).limit_denominator(1001)
            output_setting.output_frame_rate = unreal.FrameRate(
                numerator=rate.numerator,
                denominator=rate.denominator,
            )

        if job not in render_queue.get_jobs():
            return unreal_error("Render queue verification failed", "The configured job is not present in the queue.")

        context = {
            "sequence_path": sequence_path,
            "map_path": map_package_path,
            "output_path": output_path,
            "resolution": f"{resolution_x}x{resolution_y}",
            "output_format": normalized_format,
            "job_status": "queued_not_started",
            "render_started": False,
            "spatial_samples": spatial_samples,
            "temporal_samples": temporal_samples,
            "ocio_enabled": ocio_path is not None,
        }
        if ocio_path is not None:
            context["ocio_config_path"] = str(ocio_path.resolve())
            context["ocio_transform"] = f"{ocio_source_color_space} -> {ocio_display} / {ocio_view}"
        if rate is not None:
            context["frame_rate_numerator"] = rate.numerator
            context["frame_rate_denominator"] = rate.denominator

        return unreal_success(
            f"Queued MRQ job for '{sequence_path}' ({resolution_x}x{resolution_y}, {normalized_format}); render not started",
            **context,
            prompt="Open Window -> Movie Render Queue to review and start the queued job.",
        )

    except Exception as exc:
        if render_queue is not None and job is not None:
            try:
                render_queue.delete_job(job)
            except Exception:
                pass
        return unreal_from_exception(
            exc,
            f"Failed to queue MRQ job for '{sequence_path}'",
            sequence_path=sequence_path,
            output_path=output_path,
            possible_solutions=[
                "Enable the Movie Render Queue plugin and the output plugin required by the selected format.",
                "Open Window -> Movie Render Queue and verify the sequence and map manually.",
            ],
        )
