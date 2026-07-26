"""Control the Play-In-Editor (PIE) session lifecycle.

Supports: enter, pause, resume, exit/stop. Uses Unreal Engine's editor subsystem
or console commands — no OS-level input dependency.
"""

from __future__ import annotations

from _pie_helpers import get_level_editor_subsystem, get_pie_world, is_pie_active, is_pie_paused
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_error, unreal_from_exception, unreal_success

# Valid actions
_VALID_ACTIONS = {"enter", "pause", "resume", "exit", "stop"}


def _pie_enter() -> dict:
    """Start a new PIE session."""
    editor_subsystem = get_level_editor_subsystem()
    if editor_subsystem is None:
        return unreal_error(
            "LevelEditorSubsystem is unavailable",
            "Cannot access the editor subsystem to control PIE",
            possible_solutions=[
                "Ensure the Unreal Editor is running.",
                "Use the editor UI to start PIE manually.",
            ],
        )

    if is_pie_active():
        return unreal_success(
            "PIE is already running",
            prompt="Use pie_control with action=pause or action=exit to manage the session.",
            pie_state="running",
            pie_paused=is_pie_paused(),
        )

    editor_subsystem.editor_request_begin_play()
    return unreal_success(
        "PIE start requested",
        prompt="Use pie_get_status to verify that PIE entered the playing state.",
        pie_state="starting",
    )


def _pie_pause() -> dict:
    """Pause the active PIE session."""
    import unreal  # noqa: PLC0415

    if not is_pie_active():
        return unreal_error(
            "No active PIE session to pause",
            possible_solutions=["Start PIE first with action=enter."],
        )

    if is_pie_paused():
        return unreal_success(
            "PIE is already paused",
            pie_state="paused",
        )

    world = get_pie_world()
    if world is None or not unreal.GameplayStatics.set_game_paused(world, True):
        return unreal_error("Failed to pause the active PIE session")

    return unreal_success(
        "PIE session paused",
        prompt="Use pie_control with action=resume to continue, or action=exit to stop.",
        pie_state="paused",
    )


def _pie_resume() -> dict:
    """Resume a paused PIE session."""
    import unreal  # noqa: PLC0415

    if not is_pie_active():
        return unreal_error(
            "No active PIE session to resume",
            possible_solutions=["Start PIE first with action=enter."],
        )

    if not is_pie_paused():
        return unreal_success(
            "PIE is already running (not paused)",
            pie_state="running",
        )

    world = get_pie_world()
    if world is None or not unreal.GameplayStatics.set_game_paused(world, False):
        return unreal_error("Failed to resume the paused PIE session")

    return unreal_success(
        "PIE session resumed",
        prompt="PIE is running. Use pie_inject_input for controlled actions.",
        pie_state="running",
    )


def _pie_exit() -> dict:
    """Exit/stop the active PIE session."""

    editor_subsystem = get_level_editor_subsystem()
    if editor_subsystem is None:
        return unreal_error("LevelEditorSubsystem is unavailable")

    if not is_pie_active():
        return unreal_error(
            "No active PIE session to exit",
            possible_solutions=["Start PIE first with action=enter."],
        )

    editor_subsystem.editor_request_end_play()
    return unreal_success(
        "PIE stop requested",
        prompt="Use pie_get_status to verify that PIE returned to the stopped state.",
        pie_state="stopping",
    )


_ACTION_MAP = {
    "enter": _pie_enter,
    "pause": _pie_pause,
    "resume": _pie_resume,
    "exit": _pie_exit,
    "stop": _pie_exit,
}


@skill_entry
def pie_control(action: str = "", **kwargs) -> dict:
    """Control the Play-In-Editor session lifecycle.

    Args:
        action: One of enter, pause, resume, exit, stop.
    """
    if not action or not str(action).strip():
        return missing_param_error("action")

    action = str(action).strip().lower()
    if action not in _VALID_ACTIONS:
        return unreal_error(
            "Invalid PIE action: '{}'".format(action),
            "Must be one of: {}".format(", ".join(sorted(_VALID_ACTIONS))),
            possible_solutions=["Pass a valid action: enter, pause, resume, exit, stop."],
        )

    handler = _ACTION_MAP.get(action)
    if handler is None:
        return unreal_error("No handler for action '{}'".format(action))

    try:
        return handler()
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to {} PIE".format(action))
