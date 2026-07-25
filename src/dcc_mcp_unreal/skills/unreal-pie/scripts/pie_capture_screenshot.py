"""Capture a viewport screenshot to a PNG file.

Uses Unreal Engine's AutomationLibrary (take_high_res_screenshot) when available,
falls back to the HighResShot console command. Saves to the specified path or a
timestamped default in the project Saved/Screenshots directory.
"""

from __future__ import annotations

import os
import time

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success


def _ensure_dir(filepath: str) -> str:
    """Ensure the parent directory exists; return normalized path."""
    directory = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(directory, exist_ok=True)
    return os.path.abspath(filepath)


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
            unreal.AutomationLibrary.take_high_res_screenshot(
                resolution_x if resolution_x > 0 else 0,
                resolution_y if resolution_y > 0 else 0,
                filepath,
            )
            return unreal_success(
                "Screenshot captured via AutomationLibrary",
                filepath=filepath,
                resolution_x=resolution_x,
                resolution_y=resolution_y,
            )

        # Fallback: HighResShot console command
        world = unreal.EditorLevelLibrary.get_editor_world()
        if resolution_x > 0 and resolution_y > 0:
            cmd = "HighResShot {}x{} filename={}".format(int(resolution_x), int(resolution_y), filepath)
        else:
            cmd = "HighResShot filename={}".format(filepath)

        unreal.SystemLibrary.execute_console_command(world, cmd)

        return unreal_success(
            "Screenshot captured via console command",
            prompt="Screenshot saved. Verify the file at: {}".format(filepath),
            filepath=filepath,
            method="console_command",
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to capture screenshot to {}".format(filepath))
