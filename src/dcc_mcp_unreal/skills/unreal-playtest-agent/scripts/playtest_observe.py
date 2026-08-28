"""Observe a structured PIE playtest episode."""

from __future__ import annotations

from _playtest_runtime import get_episode, observe_episode, playtest_failure
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_success


@skill_entry
def playtest_observe(episode_id: str = "", **kwargs) -> dict:
    if not episode_id:
        return missing_param_error("episode_id")
    try:
        episode = get_episode(episode_id)
        return unreal_success(
            "Collected structured PIE playtest observation",
            episode_id=episode_id,
            observation=observe_episode(episode),
        )
    except BaseException as exc:
        return playtest_failure(exc, "Failed to observe the structured PIE playtest episode")
