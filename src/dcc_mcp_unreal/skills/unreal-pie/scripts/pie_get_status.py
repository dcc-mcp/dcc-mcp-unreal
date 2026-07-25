"""Query PIE session state and performance counters.

Reports PIE state (playing/paused/stopped) and samples performance metrics:
FPS, frame time, game/render thread time, GPU time, and memory when available.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success

from _pie_helpers import is_pie_active, is_pie_paused


def _get_pie_state() -> dict:
    """Determine the current PIE state."""
    if not is_pie_active():
        return {"state": "stopped", "paused": False}
    if is_pie_paused():
        return {"state": "paused", "paused": True}
    return {"state": "playing", "paused": False}


def _get_perf_stats() -> dict:
    """Collect performance counters from Unreal Engine.

    Uses the stat subsystem (stat unit, stat fps) and engine version info.
    """
    import unreal  # noqa: PLC0415

    stats = {}

    # Engine version
    try:
        stats["engine_version"] = str(unreal.SystemLibrary.get_engine_version())
    except Exception:
        stats["engine_version"] = "unknown"

    # Project name
    try:
        stats["project_name"] = unreal.Paths.get_project_file_path()
    except Exception:
        stats["project_name"] = ""

    # Level name
    try:
        world = unreal.EditorLevelLibrary.get_editor_world()
        if world is not None:
            stats["level_name"] = str(world.get_name())
    except Exception:
        stats["level_name"] = ""

    # FPS via stat console command capture is not directly accessible from
    # Python — we approximate with known metrics where available.
    try:
        if hasattr(unreal, "CoreGlobals"):
            stats["note"] = "FPS/memory stats require a C++ bridge. See DccMcpAutomationLibrary."
    except Exception:
        pass

    # Try C++ automation bridge for richer stats
    try:
        library = getattr(unreal, "DccMcpAutomationLibrary", None)
        if library is not None and hasattr(library, "get_performance_stats_json"):
            import json

            perf_json = library.get_performance_stats_json()
            perf = json.loads(perf_json)
            stats.update(perf)
    except Exception:
        pass

    # Try stat fps toggling (not reliable but informative)
    try:
        engine_version = stats.get("engine_version", "")
        if "5." in engine_version:
            stats["stat_commands_available"] = [
                "stat fps",
                "stat unit",
                "stat game",
                "stat gpu",
                "stat memory",
            ]
    except Exception:
        pass

    return stats


@skill_entry
def pie_get_status(**kwargs) -> dict:
    """Query the current PIE session state and performance counters.

    Returns PIE state, engine version, level name, and any available
    performance metrics.
    """
    try:
        pie_state = _get_pie_state()
        perf_stats = _get_perf_stats()

        return unreal_success(
            "PIE state: {}".format(pie_state["state"]),
            prompt="Use pie_control to change state, pie_capture_screenshot for visual evidence.",
            pie_state=pie_state["state"],
            pie_paused=pie_state["paused"],
            perf=perf_stats,
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to query PIE status")
