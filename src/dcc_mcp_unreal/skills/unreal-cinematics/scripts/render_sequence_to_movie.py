"""Queue a Level Sequence for cinematic rendering via the Movie Render Queue."""

from __future__ import annotations

from fractions import Fraction

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success

_OUTPUT_CLASSES = {
    "png": "MoviePipelineImageSequenceOutput_PNG",
    "jpg": "MoviePipelineImageSequenceOutput_JPG",
    "jpeg": "MoviePipelineImageSequenceOutput_JPG",
    "exr": "MoviePipelineImageSequenceOutput_EXR",
}


@skill_entry
def render_sequence_to_movie(
    sequence_path: str,
    output_path: str,
    resolution_x: int = 1920,
    resolution_y: int = 1080,
    output_format: str = "png",
    frame_rate_override: float = 0.0,
    **kwargs,
) -> dict:
    """Queue a Level Sequence for rendering via the Movie Render Queue.

    Args:
        sequence_path: Package path to the Level Sequence.
        output_path: Absolute output directory for rendered frames/video.
        resolution_x: Horizontal resolution in pixels.
        resolution_y: Vertical resolution in pixels.
        output_format: Output format: png, jpg, or exr.
        frame_rate_override: Override frame rate; 0 = use sequence default.

    Returns:
        ActionResultModel dict with render job status.
    """
    if not sequence_path or not sequence_path.startswith("/Game"):
        return unreal_error(
            "Invalid sequence_path",
            "sequence_path must start with /Game",
        )
    if not output_path:
        return unreal_error(
            "output_path is required",
            "Provide an absolute output directory for rendered frames.",
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

        # Get or create the Movie Render Queue subsystem
        mrq_subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        if mrq_subsystem is None:
            return unreal_error(
                "Movie Render Queue unavailable",
                "MoviePipelineQueueSubsystem could not be obtained. Enable the Movie Render Queue plugin.",
            )

        render_queue = mrq_subsystem.get_queue()
        if render_queue is None:
            return unreal_error(
                "Render queue is null",
                "Could not obtain the movie render queue.",
            )

        output_class = getattr(unreal, _OUTPUT_CLASSES[normalized_format], None)
        if output_class is None:
            return unreal_error(
                "Movie Render Queue output unavailable",
                f"{_OUTPUT_CLASSES[normalized_format]} is unavailable. Enable the Movie Render Queue render passes plugin.",
            )

        # Create a job for the sequence
        job = render_queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
        if job is None:
            return unreal_error("Failed to allocate render job", "Job allocation returned None.")

        job.sequence = unreal.SoftObjectPath(sequence_path)
        job.map = unreal.SoftObjectPath(unreal.EditorLevelLibrary.get_editor_world().get_path_name())

        # Configure output settings through the job's config
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
        if frame_rate_override > 0:
            rate = Fraction(str(frame_rate_override)).limit_denominator(1001)
            output_setting.output_frame_rate = unreal.FrameRate(
                numerator=rate.numerator,
                denominator=rate.denominator,
            )

        # Save the job
        mrq_subsystem.save_queue()

        job_info = {
            "sequence_path": sequence_path,
            "output_path": output_path,
            "resolution": f"{resolution_x}x{resolution_y}",
            "output_format": normalized_format,
            "job_status": "queued",
        }

        return unreal_success(
            f"Queued render job for '{sequence_path}' ({resolution_x}x{resolution_y}, {normalized_format})",
            **job_info,
            prompt="Open Window → Movie Render Queue to monitor and start the render. The job is queued but not yet started.",
        )

    except Exception as exc:
        if render_queue is not None and job is not None:
            try:
                render_queue.delete_job(job)
            except Exception:
                pass
        return unreal_from_exception(
            exc,
            f"Failed to queue render job for '{sequence_path}'",
            sequence_path=sequence_path,
            output_path=output_path,
            possible_solutions=[
                "Enable the Movie Render Queue and Movie Render Queue Additional Render Passes plugins.",
                "Open Window → Movie Render Queue and verify the sequence and map manually.",
            ],
        )
