"""Validate the active Unreal MCP server without restarting it."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import uuid
from importlib import metadata
from pathlib import Path

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


def _canonical_engine_version(value: object) -> str:
    match = re.match(r"^(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})(?:[-+].*)?$", str(value))
    if match is None:
        raise ValueError("Unreal returned a noncanonical engine version")
    return ".".join(match.groups())


def _module_origin(module, package: str) -> str:
    origin = Path(str(getattr(module, "__file__", ""))).resolve()
    if not origin.is_file() or origin.stat().st_size <= 0 or origin.parent.name != package:
        raise ValueError(f"{package} runtime module origin is missing or invalid")
    return str(origin)


def _install_identity(server) -> dict:
    import dcc_mcp_core  # noqa: PLC0415
    import init_unreal  # noqa: PLC0415

    import dcc_mcp_unreal  # noqa: PLC0415
    import unreal  # noqa: PLC0415

    instance_id = str(uuid.UUID(str(getattr(server, "instance_id", ""))))
    process_start_token = getattr(init_unreal, "PROCESS_START_TOKEN", None)
    if not isinstance(process_start_token, str) or re.fullmatch(r"[A-Fa-f0-9]{32}", process_start_token) is None:
        raise ValueError("Unreal bootstrap process token is missing or invalid")
    editor = Path(sys.executable).resolve()
    if not editor.is_file() or editor.stat().st_size <= 0:
        raise ValueError("Unreal editor executable identity is unavailable")
    project = Path(str(unreal.Paths.get_project_file_path())).resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise ValueError("Unreal active project identity is unavailable")
    plugin_root = Path(str(unreal.PluginBlueprintLibrary.get_plugin_base_dir("DccMcpUnreal"))).resolve()
    if not plugin_root.is_dir() or not (plugin_root / "DccMcpUnreal.uplugin").is_file():
        raise ValueError("Mounted DccMcpUnreal plugin identity is unavailable")
    adapter_version = metadata.version("dcc-mcp-unreal")
    core_version = metadata.version("dcc-mcp-core")
    return {
        "instance_id": instance_id,
        "host_pid": os.getpid(),
        "process_start_token": process_start_token,
        "editor_executable": str(editor),
        "project_file": str(project),
        "plugin_root": str(plugin_root),
        "engine_version": _canonical_engine_version(unreal.SystemLibrary.get_engine_version()),
        "adapter_version": adapter_version,
        "core_version": core_version,
        "adapter_origin": _module_origin(dcc_mcp_unreal, "dcc_mcp_unreal"),
        "core_origin": _module_origin(dcc_mcp_core, "dcc_mcp_core"),
    }


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
            install_identity=_install_identity(server),
        )
    except Exception as exc:
        return unreal_from_exception(exc, "MCP server self-check failed")
