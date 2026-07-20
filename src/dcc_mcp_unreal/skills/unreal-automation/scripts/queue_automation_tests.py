"""Queue Unreal native Automation tests from MCP."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_from_exception, unreal_success


@skill_entry
def queue_automation_tests(filter: str = "", **kwargs) -> dict:
    """Queue native Unreal Automation tests via the editor console command."""
    if not filter or not str(filter).strip():
        return missing_param_error("filter")

    try:
        import unreal  # noqa: PLC0415

        world = unreal.EditorLevelLibrary.get_editor_world()
        command = "Automation RunTests {}".format(str(filter).strip())
        unreal.SystemLibrary.execute_console_command(world, command)
        return unreal_success(
            "Queued Unreal Automation tests",
            prompt="Watch the Output Log or Automation UI for completion and reports.",
            command=command,
            filter=str(filter).strip(),
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to queue Unreal Automation tests")
