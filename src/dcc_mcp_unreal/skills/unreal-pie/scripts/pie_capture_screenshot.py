"""Capture a viewport screenshot to a PNG file.

Uses Unreal Engine's AutomationLibrary (take_high_res_screenshot) outside PIE.
While PIE is running, queues the HighResShot console command against the game
world so the main-thread MCP request can return before the next frame. Saves to
the specified path or a timestamped default in Saved/Screenshots.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from _pie_helpers import create_job
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success


def _ensure_dir(filepath: str) -> str:
    """Ensure the parent directory exists; return normalized path."""
    directory = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(directory, exist_ok=True)
    return os.path.abspath(filepath)


def _create_screenshot_job(filepath: str, method: str) -> str:
    """Record the pre-request artifact signature so stale files cannot complete a new job."""
    path = Path(filepath)
    stat = path.stat() if path.is_file() else None
    return create_job(
        "screenshot",
        filepath,
        filepath=filepath,
        method=method,
        baseline_mtime_ns=stat.st_mtime_ns if stat else None,
        baseline_size=stat.st_size if stat else None,
    )


def _default_screenshot_path() -> str:
    """Generate a default screenshot path in the project's Saved directory."""
    try:
        import unreal  # noqa: PLC0415

        project_dir = unreal.Paths.project_dir()
        saved_dir = os.path.join(project_dir, "Saved", "Screenshots")
        os.makedirs(saved_dir, exist_ok=True)
    except Exception:
        saved_dir = os.path.join(os.getcwd(), "Screenshots")
        os.makedirs(saved_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(saved_dir, "pie_{}.png".format(timestamp))


def _is_playing_in_editor(unreal) -> bool:
    """Return whether PIE is active without assuming every supported UE API exists."""
    get_subsystem = getattr(unreal, "get_editor_subsystem", None)
    subsystem_type = getattr(unreal, "LevelEditorSubsystem", None)
    if not callable(get_subsystem) or subsystem_type is None:
        return False

    subsystem = get_subsystem(subsystem_type)
    is_playing = getattr(subsystem, "is_in_play_in_editor", None)
    return bool(is_playing()) if callable(is_playing) else False


def _capture_world(unreal, playing_in_editor: bool):
    """Resolve the game world during PIE and the editor world otherwise."""
    get_subsystem = getattr(unreal, "get_editor_subsystem", None)
    subsystem_type = getattr(unreal, "UnrealEditorSubsystem", None)
    if callable(get_subsystem) and subsystem_type is not None:
        subsystem = get_subsystem(subsystem_type)
        getter_name = "get_game_world" if playing_in_editor else "get_editor_world"
        getter = getattr(subsystem, getter_name, None)
        if callable(getter):
            world = getter()
            if world is not None:
                return world

    return unreal.EditorLevelLibrary.get_editor_world()


@skill_entry
def pie_capture_screenshot(
    filepath: str = "",
    resolution_x: int = 0,
    resolution_y: int = 0,
    **kwargs,
) -> dict:
    """Capture the active viewport to a PNG file.

    Args:
        filepath: Absolute path for the output PNG. Auto-generated if empty.
        resolution_x: Viewport width override (0 = current size).
        resolution_y: Viewport height override (0 = current size).
    """
    # Resolve filepath
    if not filepath or not str(filepath).strip():
        filepath = _default_screenshot_path()
    else:
        filepath = str(filepath).strip()
        if not filepath.lower().endswith(".png"):
            filepath += ".png"

    try:
        filepath = _ensure_dir(filepath)
    except OSError as exc:
        return unreal_error(
            "Cannot create screenshot directory",
            str(exc),
            possible_solutions=["Check that the target path is writable."],
        )

    try:
        import unreal  # noqa: PLC0415

        playing_in_editor = _is_playing_in_editor(unreal)

        # AutomationLibrary can wait for a later frame while its Python call still owns
        # Unreal's main thread. During PIE, use the queue-only console path so the MCP
        # request returns immediately and callers can poll the adapter-owned job.
        if (
            not playing_in_editor
            and hasattr(unreal, "AutomationLibrary")
            and hasattr(unreal.AutomationLibrary, "take_high_res_screenshot")
        ):
            job_id = _create_screenshot_job(filepath, "automation_library")
            unreal.AutomationLibrary.take_high_res_screenshot(
                resolution_x if resolution_x > 0 else 0,
                resolution_y if resolution_y > 0 else 0,
                filepath,
            )
            return unreal_success(
                "Screenshot capture requested via AutomationLibrary",
                prompt="Wait for the screenshot file to exist at: {}".format(filepath),
                filepath=filepath,
                job_id=job_id,
                method="automation_library",
                capture_pending=True,
                resolution_x=resolution_x,
                resolution_y=resolution_y,
            )

        # Fallback: HighResShot console command
        world = _capture_world(unreal, playing_in_editor)
        if resolution_x > 0 and resolution_y > 0:
            cmd = "HighResShot {}x{} filename={}".format(int(resolution_x), int(resolution_y), filepath)
        else:
            cmd = "HighResShot filename={}".format(filepath)

        job_id = _create_screenshot_job(filepath, "console_command")
        unreal.SystemLibrary.execute_console_command(world, cmd)

        return unreal_success(
            "Screenshot capture requested via console command",
            prompt="Wait for the screenshot file to exist at: {}".format(filepath),
            filepath=filepath,
            job_id=job_id,
            method="console_command",
            capture_pending=True,
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to capture screenshot to {}".format(filepath))
