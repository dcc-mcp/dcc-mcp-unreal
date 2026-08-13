"""Capture a viewport screenshot to a PNG file.

Uses Unreal Engine's AutomationLibrary (take_high_res_screenshot) when available,
falls back to the HighResShot console command. Saves to the specified path or a
timestamped default in the project Saved/Screenshots directory.
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

        # Preferred path: AutomationLibrary high-res screenshot
        if hasattr(unreal, "AutomationLibrary") and hasattr(unreal.AutomationLibrary, "take_high_res_screenshot"):
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
        world = unreal.EditorLevelLibrary.get_editor_world()
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
