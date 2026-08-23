"""Inspect Unreal's active Movie Render Queue."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success
from dcc_mcp_unreal.plugin_preflight import require_plugins


@skill_entry
def get_render_status(**_kwargs) -> dict:
    try:
        import unreal  # noqa: PLC0415

        preflight_error = require_plugins(unreal, "movie_render_queue")
        if preflight_error is not None:
            return preflight_error

        subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        if subsystem is None:
            return unreal_error("Movie Render Queue unavailable", "MoviePipelineQueueSubsystem is unavailable")
        jobs = list(subsystem.get_queue().get_jobs())
        rendering = bool(subsystem.is_rendering())
        return unreal_success(
            "Movie Render Queue is rendering" if rendering else "Movie Render Queue is idle",
            is_rendering=rendering,
            queued_jobs=len(jobs),
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to inspect Movie Render Queue")


def main(**kwargs) -> dict:
    return get_render_status(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
