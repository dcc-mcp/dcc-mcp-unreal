"""Poll the status and results of a previously queued Automation Test job.

Checks the in-memory job registry and, when possible, queries the native
Automation Test framework for completion evidence.
"""

from __future__ import annotations

from _pie_helpers import get_job, update_job
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_error, unreal_from_exception, unreal_success


def _check_native_completion(job: dict) -> dict:
    """Check with the native automation library whether the test has finished.

    If the C++ bridge reports completion, update the job in the registry.
    """
    import json

    import unreal  # noqa: PLC0415

    filter_str = job.get("filter", "")

    library = getattr(unreal, "DccMcpAutomationLibrary", None)
    if library is not None and hasattr(library, "poll_automation_results_json"):
        try:
            result_json = library.poll_automation_results_json(filter_str)
            result = json.loads(result_json)
            if result.get("completed", False):
                # Tests finished — update job with results
                success = not result.get("has_failures", False)
                update_job(
                    job["job_id"],
                    status="completed" if success else "failed",
                    result=result,
                )
                return result
        except Exception:
            pass

    # Fallback: try listing tests via C++ bridge to detect completion
    if library is not None and hasattr(library, "list_automation_tests_json"):
        try:
            list_json = library.list_automation_tests_json(filter_str)
            tests = json.loads(list_json)
            test_items = tests.get("tests", [])
            if test_items:
                # Check if all tests have a result state
                all_done = all(t.get("state") in ("Success", "Fail", "Skipped", "NotRun") for t in test_items)
                if all_done and test_items:
                    has_failures = any(t.get("state") == "Fail" for t in test_items)
                    update_job(
                        job["job_id"],
                        status="failed" if has_failures else "completed",
                        result=tests,
                    )
        except Exception:
            pass

    return None


@skill_entry
def pie_poll_test(job_id: str = "", **kwargs) -> dict:
    """Poll a previously queued Automation Test job for results.

    Args:
        job_id: The job_id returned by pie_run_test.
    """
    if not job_id or not str(job_id).strip():
        return missing_param_error("job_id")

    job_id = str(job_id).strip()

    try:
        job = get_job(job_id)
        if job is None:
            return unreal_error(
                "Job not found: {}".format(job_id),
                possible_solutions=[
                    "Verify the job_id from pie_run_test.",
                    "Jobs are in-memory and lost on editor restart.",
                ],
            )

        # If still running/queued, check for native completion
        if job.get("status") in ("queued", "running"):
            _check_native_completion(job)
            # Reload after potential update
            job = get_job(job_id)

        status = job.get("status", "unknown") if job else "unknown"

        return unreal_success(
            "Job {} status: {}".format(job_id, status),
            prompt=_poll_prompt(status, job_id),
            job_id=job_id,
            status=status,
            job_type=job.get("job_type", "") if job else "",
            filter=job.get("filter", "") if job else "",
            result=job.get("result") if job else None,
            error=job.get("error") if job else None,
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to poll job {}".format(job_id))


def _poll_prompt(status: str, job_id: str) -> str:
    """Generate a follow-up prompt based on job status."""
    if status == "completed":
        return "Test completed successfully. Review the result field for details."
    elif status == "failed":
        return "Test run finished with failures. Check the result and use pie_snapshot_log for error details."
    elif status == "cancelled":
        return "Job was cancelled. Queue a new test with pie_run_test if needed."
    elif status in ("queued", "running"):
        return "Job still in progress. Poll again with pie_poll_test job_id={}.".format(job_id)
    else:
        return "Unknown job status. Check the Automation Test UI in Unreal Editor."
