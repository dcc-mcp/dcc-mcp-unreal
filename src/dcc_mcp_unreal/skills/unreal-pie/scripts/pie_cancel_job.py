"""Cancel a previously queued job.

Marks the job as cancelled in the in-memory registry. Does not force-kill
the Unreal process — native Automation Tests continue to completion but
their results are discarded.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_error, unreal_success

from _pie_helpers import cancel_job, get_job, list_jobs


@skill_entry
def pie_cancel_job(job_id: str = "", **kwargs) -> dict:
    """Cancel a previously queued job by job_id.

    Args:
        job_id: The job_id to cancel (from pie_run_test).
    """
    if not job_id or not str(job_id).strip():
        return missing_param_error("job_id")

    job_id = str(job_id).strip()

    job = get_job(job_id)
    if job is None:
        # List active jobs to help the agent find the right ID
        active = list_jobs()
        active_ids = [
            "{} ({})".format(j["job_id"], j.get("status", "?"))
            for j in active
            if j.get("status") in ("queued", "running")
        ]
        return unreal_error(
            "Job not found: {}".format(job_id),
            possible_solutions=[
                "Verify the job_id from pie_run_test.",
                "Active jobs: {}".format(active_ids if active_ids else "none"),
            ],
        )

    status = job.get("status")
    if status in ("completed", "failed", "cancelled"):
        return unreal_success(
            "Job {} already in terminal state: {}".format(job_id, status),
            job_id=job_id,
            status=status,
        )

    cancelled = cancel_job(job_id)
    return unreal_success(
        "Job {} cancelled".format(job_id),
        prompt="The job is marked cancelled. Queue a new test with pie_run_test if needed.",
        job_id=job_id,
        status="cancelled",
        cancelled_at=cancelled.get("updated_at") if cancelled else None,
    )
