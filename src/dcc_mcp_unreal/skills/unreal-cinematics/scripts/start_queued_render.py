"""Start Unreal's active Movie Render Queue."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success
from dcc_mcp_unreal.plugin_preflight import require_plugins

_executor = None


@skill_entry
def start_queued_render(**_kwargs) -> dict:
    try:
        import unreal  # noqa: PLC0415

        preflight_error = require_plugins(unreal, "movie_render_queue")
        if preflight_error is not None:
            return preflight_error

        global _executor
        subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        if subsystem is None:
            return unreal_error("Movie Render Queue unavailable", "MoviePipelineQueueSubsystem is unavailable")
        if subsystem.is_rendering():
            return unreal_error("Movie Render Queue is already rendering", "Wait for the active render to finish")
        jobs = list(subsystem.get_queue().get_jobs())
        if not jobs:
            return unreal_error("Movie Render Queue is empty", "Queue a sequence before starting the render")

        for command in (
            "r.MotionBlurQuality 4",
            "r.DepthOfFieldQuality 4",
            "r.Lumen.Reflections.Quality 4",
            "r.Lumen.ScreenProbeGather.Quality 4",
        ):
            unreal.SystemLibrary.execute_console_command(None, command)
        _executor = unreal.MoviePipelinePIEExecutor()
        subsystem.render_queue_with_executor_instance(_executor)
        return unreal_success(
            f"Started {len(jobs)} Movie Render Queue job(s)",
            render_started=True,
            queued_jobs=len(jobs),
            prompt="Poll get_render_status and verify the configured output directory.",
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to start Movie Render Queue")


def main(**kwargs) -> dict:
    return start_queued_render(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
