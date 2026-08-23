"""Cancel Unreal's active Movie Render Queue executor."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success
from dcc_mcp_unreal.plugin_preflight import require_plugins


@skill_entry
def cancel_queued_render(**_kwargs) -> dict:
    """Request cancellation of the active render and all queued jobs."""
    try:
        import unreal  # noqa: PLC0415

        preflight_error = require_plugins(unreal, "movie_render_queue")
        if preflight_error is not None:
            return preflight_error

        subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        if subsystem is None:
            return unreal_error("Movie Render Queue unavailable", "MoviePipelineQueueSubsystem is unavailable")
        executor = subsystem.get_active_executor()
        if executor is None or not subsystem.is_rendering():
            return unreal_error("Movie Render Queue is idle", "There is no active render to cancel")
        executor.cancel_all_jobs()
        return unreal_success(
            "Requested cancellation of the active Movie Render Queue",
            cancellation_requested=True,
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to cancel Movie Render Queue")


def main(**kwargs) -> dict:
    return cancel_queued_render(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
