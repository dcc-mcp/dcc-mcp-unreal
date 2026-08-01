"""Shared helpers for the unreal-pie skill package.

Provides in-memory job tracking for async Automation Test runs and PIE-related
utility functions. All state is session-scoped (lives in the Python interpreter
lifetime) — no persistence across editor restarts.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# In-memory job registry
# ---------------------------------------------------------------------------

_job_registry: Dict[str, Dict[str, Any]] = {}


def create_job(job_type: str, filter_str: str = "", **extra: Any) -> str:
    """Create a new job entry and return its job_id.

    Args:
        job_type: Short type tag, e.g. "automation_test".
        filter_str: Automation test filter or human-readable label.
        **extra: Arbitrary metadata stored with the job.

    Returns:
        A unique job_id string.
    """
    job_id = "pie_{}_{}_{}".format(
        job_type,
        time.strftime("%Y%m%d_%H%M%S"),
        uuid.uuid4().hex[:8],
    )
    _job_registry[job_id] = {
        "job_id": job_id,
        "job_type": job_type,
        "filter": filter_str,
        "status": "queued",
        "created_at": time.time(),
        "updated_at": time.time(),
        "result": None,
        "error": None,
        **extra,
    }
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Return the job dict for *job_id*, or None."""
    return _job_registry.get(job_id)


def update_job(job_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """Update fields on a job. Returns the updated dict or None if not found."""
    job = _job_registry.get(job_id)
    if job is None:
        return None
    job.update(fields)
    job["updated_at"] = time.time()
    return job


def cancel_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Mark a job as cancelled. Returns the updated dict or None."""
    return update_job(job_id, status="cancelled")


def list_jobs(job_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all tracked jobs, optionally filtered by type."""
    jobs = list(_job_registry.values())
    if job_type:
        jobs = [j for j in jobs if j.get("job_type") == job_type]
    jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    return jobs


def complete_job(job_id: str, result: Any = None, status: str = "completed") -> Optional[Dict[str, Any]]:
    """Mark a job as completed with a result."""
    return update_job(job_id, status=status, result=result)


def fail_job(job_id: str, error: str = "") -> Optional[Dict[str, Any]]:
    """Mark a job as failed with an error message."""
    return update_job(job_id, status="failed", error=error)


# ---------------------------------------------------------------------------
# PIE helpers
# ---------------------------------------------------------------------------


def get_level_editor_subsystem():
    """Return Unreal's scriptable Level Editor subsystem, or None."""
    try:
        import unreal  # noqa: PLC0415

        return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    except Exception:
        return None


def get_pie_world():
    """Return the PIE world if a PIE session is active, else the editor world.

    Returns:
        A ``unreal.World`` object or None.
    """
    try:
        import unreal  # noqa: PLC0415

        editor_subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        if editor_subsystem is not None:
            pie_world = editor_subsystem.get_game_world()
            if pie_world is not None:
                return pie_world
            return editor_subsystem.get_editor_world()
        return unreal.EditorLevelLibrary.get_editor_world()
    except Exception:
        return None


def is_pie_active() -> bool:
    """Return True if a PIE session is currently active (playing or paused)."""
    try:
        editor_subsystem = get_level_editor_subsystem()
        return bool(editor_subsystem and editor_subsystem.is_in_play_in_editor())
    except Exception:
        return False


def is_pie_paused() -> bool:
    """Return True if the PIE session is currently paused."""
    try:
        import unreal  # noqa: PLC0415

        world = get_pie_world() if is_pie_active() else None
        return bool(world and unreal.GameplayStatics.is_game_paused(world))
    except Exception:
        return False


def run_console_command(command: str) -> bool:
    """Execute a console command on the current world.

    Args:
        command: The console command string.

    Returns:
        True if the command was executed.
    """
    try:
        import unreal  # noqa: PLC0415

        world = get_pie_world()
        if world is None:
            world = unreal.EditorLevelLibrary.get_editor_world()
        if world is not None:
            unreal.SystemLibrary.execute_console_command(world, command)
            return True
        return False
    except Exception:
        return False
