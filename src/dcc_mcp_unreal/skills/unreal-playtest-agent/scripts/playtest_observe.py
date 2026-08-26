"""Observe a structured PIE playtest episode."""

from __future__ import annotations

from _playtest_runtime import get_episode, observe
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_from_exception, unreal_success
from dcc_mcp_unreal.pie_session import PieSessionUnavailableError, pie_session_error


@skill_entry
def playtest_observe(episode_id: str = "", **kwargs) -> dict:
    if not episode_id:
        return missing_param_error("episode_id")
    try:
        episode = get_episode(episode_id)
        return unreal_success(
            "Collected structured PIE playtest observation",
            episode_id=episode_id,
            observation=observe(episode["selectors"]),
        )
    except PieSessionUnavailableError as exc:
        return pie_session_error(exc)
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to observe the structured PIE playtest episode")
