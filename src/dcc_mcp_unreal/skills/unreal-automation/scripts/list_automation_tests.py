"""List Unreal native Automation tests through the plugin C++ bridge."""

from __future__ import annotations

import json

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success


@skill_entry
def list_automation_tests(filter: str = "", **kwargs) -> dict:
    """List Automation Test Framework tests registered in the current editor."""
    try:
        import unreal  # noqa: PLC0415

        library = getattr(unreal, "DccMcpAutomationLibrary", None)
        if library is None or not hasattr(library, "list_automation_tests_json"):
            return unreal_error(
                "DCC MCP native automation bridge is not available",
                "unreal.DccMcpAutomationLibrary.list_automation_tests_json is missing",
                possible_solutions=[
                    "Run from the packaged DccMcpUnreal plugin with its C++ module compiled.",
                    "Use UnrealEditor-Cmd once to build the project plugin module.",
                ],
            )

        payload = json.loads(library.list_automation_tests_json(filter or ""))
        tests = payload.get("tests", [])
        return unreal_success(
            "Found {} Automation test(s)".format(len(tests)),
            prompt="Use queue_automation_tests with a narrow filter to run a test set.",
            filter=payload.get("filter", filter or ""),
            count=len(tests),
            tests=tests,
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to list Unreal Automation tests")
