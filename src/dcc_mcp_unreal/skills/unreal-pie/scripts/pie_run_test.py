"""Queue an Automation Test run and return a job_id for async polling.

The test runs in Unreal's native Automation Test framework. The job_id can be
polled via pie_poll_test and cancelled via pie_cancel_job.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_error, unreal_from_exception, unreal_success

from _pie_helpers import create_job, get_job, update_job


@skill_entry
def pie_run_test(filter: str = "", **kwargs) -> dict:
    """Queue a native Unreal Automation Test by filter string.

    Returns a job_id for polling via pie_poll_test.

    Args:
        filter: Automation test name or filter, e.g. "DccMcp.Smoke".
    """
    if not filter or not str(filter).strip():
        return missing_param_error("filter")

    filter_str = str(filter).strip()

    try:
        import unreal  # noqa: PLC0415

        # Create a tracked job
        job_id = create_job("automation_test", filter_str)

        # Try the C++ automation library if available
        library = getattr(unreal, "DccMcpAutomationLibrary", None)
        if library is not None and hasattr(library, "queue_automation_tests_json"):
            import json

            result = library.queue_automation_tests_json(filter_str)
            parsed = json.loads(result)

            # If the library reports synchronous completion, capture it immediately
            if parsed.get("completed", False):
                update_job(
                    job_id,
                    status="completed",
                    result=parsed,
                )
                return unreal_success(
                    "Automation test completed synchronously",
                    job_id=job_id,
                    status="completed",
                    result=parsed,
                )

            update_job(job_id, status="running", native_result=parsed)
        else:
            # Fallback: use console command
            world = unreal.EditorLevelLibrary.get_editor_world()
            command = "Automation RunTests {}".format(filter_str)
            unreal.SystemLibrary.execute_console_command(world, command)
            update_job(job_id, status="running")

        job = get_job(job_id)
        return unreal_success(
            "Automation test queued: {}".format(filter_str),
            prompt="Poll results with pie_poll_test using job_id={}. Monitor logs with pie_snapshot_log.".format(
                job_id
            ),
            job_id=job_id,
            filter=filter_str,
            status=job.get("status") if job else "unknown",
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to queue Automation Test '{}'".format(filter_str))
