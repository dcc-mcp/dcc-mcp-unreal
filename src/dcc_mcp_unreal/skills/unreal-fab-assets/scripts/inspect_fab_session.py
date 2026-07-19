"""Inspect the official Fab session without returning credentials."""

from __future__ import annotations

from _fab import fab_library, inspect_session
from dcc_mcp_core.skill import skill_entry, skill_error, skill_exception, skill_success


@skill_entry
def inspect_fab_session(**kwargs) -> dict:
    try:
        status = inspect_session(fab_library())
        if not status["plugin_available"]:
            return skill_error(
                "The official Fab plugin is unavailable",
                "Enable Epic's Fab plugin and restart Unreal Editor.",
                **status,
            )
        if status["authenticated"]:
            return skill_success("Fab is available and authenticated.", **status)
        return skill_success(
            "Fab is available but requires interactive login.",
            prompt="Call request_fab_login, complete Epic sign-in yourself, then inspect the session again.",
            next_tool="unreal_fab_assets__request_fab_login",
            **status,
        )
    except Exception as exc:
        return skill_exception(exc, message="Failed to inspect the official Fab session")


def main(**kwargs) -> dict:
    return inspect_fab_session(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
