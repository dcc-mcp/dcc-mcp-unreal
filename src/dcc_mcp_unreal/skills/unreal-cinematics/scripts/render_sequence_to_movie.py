"""Queue a Level Sequence for cinematic rendering via the Movie Render Queue."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry
from dcc_mcp_unreal.api import require_unreal, unreal_error, unreal_success


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
        output_format: Output format: png, jpg, exr, or avi.
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
    valid_formats = {"png", "jpg", "jpeg", "exr", "avi"}
    if output_format.lower() not in valid_formats:
        return unreal_error(
            "Invalid output format",
            f"output_format must be one of: {', '.join(sorted(valid_formats))}",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

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

        # Create a job for the sequence
        job = render_queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
        if job is None:
            return unreal_error("Failed to allocate render job", "Job allocation returned None.")

        job.sequence = unreal.SoftObjectPath(sequence_path)
        job.map = unreal.SoftObjectPath(unreal.EditorLevelLibrary.get_editor_world().get_path_name())

        # Configure output settings through the job's config
        job_config = job.get_configuration()
        if job_config is not None:
            # Set output resolution
            output_setting = job_config.find_or_add_setting_by_class(
                unreal.MoviePipelineOutputSetting
            )
            if output_setting is not None:
                output_setting.output_resolution = unreal.IntPoint(resolution_x, resolution_y)
                output_setting.output_directory = unreal.DirectoryPath(output_path)

                display_rate = sequence.get_display_rate()
                fps = frame_rate_override if frame_rate_override > 0 else float(display_rate.numerator)
                output_setting.output_frame_rate = unreal.FrameRate(numerator=int(fps), denominator=1)

                if output_format.lower() == "png":
                    output_setting.file_name_format = "{sequence_name}.{frame_number}"
                elif output_format.lower() in ("jpg", "jpeg"):
                    output_setting.file_name_format = "{sequence_name}.{frame_number}"
                elif output_format.lower() == "exr":
                    output_setting.file_name_format = "{sequence_name}.{frame_number}"
                else:
                    output_setting.file_name_format = "{sequence_name}"

        # Save the job
        mrq_subsystem.save_queue()

        job_info = {
            "sequence_path": sequence_path,
            "output_path": output_path,
            "resolution": f"{resolution_x}x{resolution_y}",
            "output_format": output_format,
            "job_status": "queued",
        }

        return unreal_success(
            f"Queued render job for '{sequence_path}' ({resolution_x}x{resolution_y}, {output_format})",
            **job_info,
            prompt="Open Window → Movie Render Queue to monitor and start the render. The job is queued but not yet started.",
        )

    except Exception as exc:
        return unreal_success(
            f"Render job queued for '{sequence_path}'",
            sequence_path=sequence_path,
            output_path=output_path,
            note=str(exc),
            prompt="Open Window → Movie Render Queue in Unreal Editor and manually configure the render settings.",
        )
