"""Execute one bounded semantic PIE playtest action."""

from __future__ import annotations

from _playtest_runtime import execute_action
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_from_exception, unreal_success
from dcc_mcp_unreal.pie_session import PieSessionUnavailableError, pie_session_error


@skill_entry
def playtest_execute_action(episode_id: str = "", action: str = "", **kwargs) -> dict:
    if not episode_id:
        return missing_param_error("episode_id")
    if not action:
        return missing_param_error("action")
    try:
        return unreal_success(
            "Structured PIE semantic action accepted",
            **execute_action(episode_id, action, **kwargs),
        )
    except PieSessionUnavailableError as exc:
        return pie_session_error(exc)
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to execute the structured PIE semantic action")
