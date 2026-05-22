"""Native Unreal Automation helpers for DCC MCP Unreal.

The C++ automation test registered by this plugin calls ``run_smoke`` through
Unreal's PythonScriptPlugin.  The same function is also used by the legacy
``-ExecutePythonScript`` smoke path so both entry points validate identical MCP
behavior.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional


def _ensure_packaged_python_on_path() -> None:
    """Add packaged or source-checkout Python paths."""
    content_python_dir = Path(__file__).resolve().parent
    plugin_root = content_python_dir.parent.parent
    plugin_python = plugin_root / "python"

    project_root = plugin_root.parent.parent if plugin_root.parent.name == "Plugins" else None
    if project_root is not None:
        _add_sys_path(project_root / "src", prepend=False)
        _add_sys_path(project_root.parent / "dcc-mcp-core" / "src", prepend=False)
        _add_sys_path(project_root.parent / "dcc-mcp-core" / "python", prepend=False)

    _add_sys_path(plugin_python, prepend=True)


def _add_sys_path(path: Path, *, prepend: bool = True) -> None:
    if path.is_dir():
        path_str = str(path)
        if path_str not in sys.path:
            if prepend:
                sys.path.insert(0, path_str)
            else:
                sys.path.append(path_str)


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")


def _wait_for_http_ready(mcp_url: str) -> dict:
    base_url = mcp_url.rsplit("/mcp", 1)[0]
    deadline = time.time() + 15
    last_error = None
    while time.time() < deadline:
        try:
            health = _http_get(base_url + "/health")
            readyz = _http_get(base_url + "/v1/readyz")
            return {"health": health, "readyz": readyz}
        except Exception as exc:  # noqa: BLE001 - surfaced after retry window
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError("HTTP health endpoints did not become ready before timeout: {}".format(last_error))


def _value(obj, key: str):
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key)
    return None


def _write_result(result_path: Optional[str], result: dict) -> None:
    if not result_path:
        return
    path = Path(result_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")


def _run_smoke_impl() -> dict:
    _ensure_packaged_python_on_path()

    import dcc_mcp_core  # noqa: PLC0415

    import dcc_mcp_unreal  # noqa: PLC0415
    import dcc_mcp_unreal.server as server_mod  # noqa: PLC0415

    # init_unreal.py may have started an automatic server already. Restart on a
    # random port so this smoke test is deterministic and avoids port 8765.
    dcc_mcp_unreal.stop_server()
    handle = dcc_mcp_unreal.start_server(port=0, server_name="unreal-smoke-test")
    server = server_mod._server_instance
    if server is None:
        raise RuntimeError("start_server did not create a server instance")

    try:
        skills = sorted(_value(summary, "name") for summary in server.list_skills() if _value(summary, "name"))
        expected_skills = {"unreal-actors", "unreal-assets", "unreal-level", "unreal-automation"}
        missing_skills = sorted(expected_skills.difference(skills))
        if missing_skills:
            raise RuntimeError("Missing built-in skills: {}".format(missing_skills))

        loaded = {name: server.is_skill_loaded(name) for name in expected_skills}
        not_loaded = sorted(name for name, ok in loaded.items() if not ok)
        if not_loaded:
            raise RuntimeError("Built-in skills were not loaded: {}".format(not_loaded))

        url = handle.mcp_url()
        http_status = _wait_for_http_ready(url)
        actions = server.list_actions()
        tool_names = sorted(_value(action, "name") for action in actions if _value(action, "name"))
        expected_tools = {
            "unreal_actors__list_actors",
            "unreal_actors__spawn_actor",
            "unreal_assets__list_assets",
            "unreal_level__get_level_info",
            "unreal_automation__mcp_self_check",
            "unreal_automation__list_automation_tests",
        }
        missing_tools = sorted(expected_tools.difference(tool_names))
        if missing_tools:
            raise RuntimeError("Missing MCP tools: {}".format(missing_tools))

        return {
            "success": True,
            "mcp_url": url,
            "dcc_mcp_core_version": getattr(dcc_mcp_core, "__version__", ""),
            "dcc_mcp_unreal_version": getattr(dcc_mcp_unreal, "__version__", ""),
            "skill_count": len(skills),
            "skills": skills,
            "tool_count": len(tool_names),
            "http_status": http_status,
            "sample_tools": tool_names[:20],
        }
    finally:
        dcc_mcp_unreal.stop_server()


def run_smoke(result_path: Optional[str] = None, raise_on_failure: bool = True) -> dict:
    """Run the MCP native smoke test and optionally write a JSON result file."""
    try:
        result = _run_smoke_impl()
    except Exception as exc:
        result = {"success": False, "error": repr(exc)}
        _write_result(result_path, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        if raise_on_failure:
            raise
        return result

    _write_result(result_path, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return result
