"""Validate the active Unreal MCP server without restarting it."""

from __future__ import annotations

import json
import urllib.request

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success


def _value(obj, key: str):
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key)
    return None


def _http_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        text = resp.read().decode("utf-8")
    try:
        return json.loads(text)
    except ValueError:
        return {"raw": text}


@skill_entry
def mcp_self_check(check_http: bool = True, **kwargs) -> dict:
    """Validate server state, built-in skills, registered tools, and HTTP readiness."""
    try:
        import dcc_mcp_unreal.server as server_mod  # noqa: PLC0415

        server = server_mod._server_instance
        if server is None or not getattr(server, "is_running", False):
            return unreal_error(
                "MCP server is not running",
                "dcc_mcp_unreal.server._server_instance is missing or stopped",
                possible_solutions=["Start the server with dcc_mcp_unreal.start_server() first."],
            )

        skills = sorted(_value(summary, "name") for summary in server.list_skills() if _value(summary, "name"))
        expected_skills = {"unreal-actors", "unreal-assets", "unreal-level", "unreal-automation"}
        missing_skills = sorted(expected_skills.difference(skills))

        loaded = {name: bool(server.is_skill_loaded(name)) for name in expected_skills if name in skills}
        not_loaded = sorted(name for name, ok in loaded.items() if not ok)

        tool_names = sorted(_value(action, "name") for action in server.list_actions() if _value(action, "name"))
        expected_tools = {
            "unreal_actors__list_actors",
            "unreal_actors__spawn_actor",
            "unreal_assets__list_assets",
            "unreal_level__get_level_info",
            "unreal_automation__mcp_self_check",
            "unreal_automation__list_automation_tests",
        }
        missing_tools = sorted(expected_tools.difference(tool_names))

        if missing_skills or not_loaded or missing_tools:
            return unreal_error(
                "MCP server self-check failed",
                "Missing skills, unloaded skills, or missing tools",
                missing_skills=missing_skills,
                not_loaded=not_loaded,
                missing_tools=missing_tools,
                skill_count=len(skills),
                tool_count=len(tool_names),
            )

        mcp_url = getattr(server, "mcp_url", None)
        http_status = {}
        if check_http and mcp_url:
            base_url = str(mcp_url).rsplit("/mcp", 1)[0]
            http_status = {
                "health": _http_get(base_url + "/health"),
                "readyz": _http_get(base_url + "/v1/readyz"),
            }

        return unreal_success(
            "MCP server self-check passed",
            prompt="Use list_automation_tests to inspect native UE tests or queue_automation_tests to trigger them.",
            mcp_url=mcp_url,
            skill_count=len(skills),
            skills=skills,
            loaded=loaded,
            tool_count=len(tool_names),
            sample_tools=tool_names[:20],
            http_status=http_status,
        )
    except Exception as exc:
        return unreal_from_exception(exc, "MCP server self-check failed")
