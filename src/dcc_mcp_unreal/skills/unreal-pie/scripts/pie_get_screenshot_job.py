"""Poll one adapter-owned screenshot job until its PNG artifact is ready."""

from __future__ import annotations

from pathlib import Path

from _pie_helpers import get_job, update_job
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_error, unreal_from_exception, unreal_success


@skill_entry
def pie_get_screenshot_job(job_id: str = "", **kwargs) -> dict:
    """Return screenshot artifact readiness for a job from pie_capture_screenshot."""
    if not job_id or not str(job_id).strip():
        return missing_param_error("job_id")
    job_id = str(job_id).strip()
    try:
        job = get_job(job_id)
        if job is None or job.get("job_type") != "screenshot":
            return unreal_error("Screenshot job not found: {}".format(job_id))
        path = Path(str(job.get("filepath", "")))
        stat = path.stat() if path.is_file() else None
        current_signature = (stat.st_mtime_ns, stat.st_size) if stat else None
        baseline_signature = (job.get("baseline_mtime_ns"), job.get("baseline_size"))
        ready = bool(stat and stat.st_size > 0 and current_signature != baseline_signature)
        size_bytes = stat.st_size if ready else 0
        status = "completed" if ready else "pending"
        if job.get("status") != status:
            job = update_job(job_id, status=status, result={"filepath": str(path), "size_bytes": size_bytes}) or job
        return unreal_success(
            "Screenshot job {} status: {}".format(job_id, status),
            prompt=(
                "Screenshot artifact is ready at: {}".format(path)
                if ready
                else "Poll pie_get_screenshot_job again with job_id={}.".format(job_id)
            ),
            job_id=job_id,
            status=status,
            artifact_ready=ready,
            filepath=str(path),
            size_bytes=size_bytes,
            method=job.get("method", ""),
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to poll screenshot job {}".format(job_id))
