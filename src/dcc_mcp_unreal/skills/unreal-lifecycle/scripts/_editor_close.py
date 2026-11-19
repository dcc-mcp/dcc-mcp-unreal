"""Thin typed routing to the opt-in native Editor lifecycle policy."""

from __future__ import annotations

import json
import re
import uuid

from dcc_mcp_core.skill import skill_error, skill_success

_SCHEMA = "dcc-unreal-editor-close/v1"
_STATES = {"disabled", "idle", "ready", "refused", "scheduled", "expired", "refused_at_execution", "close_requested"}


def _native(method: str, guard: dict | None = None) -> dict:
    try:
        import dcc_mcp_unreal.server as server_mod  # noqa: PLC0415
        import unreal  # noqa: PLC0415

        server = server_mod._server_instance
        if server is None or not server.is_running:
            return skill_error("Editor close unavailable", "MCP server is not running")
        instance_id = str(uuid.UUID(str(server.instance_id)))
        if guard is not None and guard["instance_id"] != instance_id:
            return skill_error("Editor close refused", "instance_id does not match the actual server")
        bridge = getattr(unreal, "DccMcpEditorLifecycleLibrary", None)
        call = getattr(bridge, method, None)
        if not callable(call):
            return skill_error("Editor close unavailable", "Matching native lifecycle plugin is required")
        payload = call(json.dumps(guard, ensure_ascii=False)) if guard is not None else call()
        result = json.loads(payload)
        if (
            not isinstance(result, dict)
            or result.get("schema") != _SCHEMA
            or result.get("state") not in _STATES
            or result.get("process_exit_verified") is not False
            or result.get("response_flush_verified") is not False
        ):
            return skill_error("Editor close unavailable", "Invalid native lifecycle response")
        # Native ownership comes from startup, never from these caller expectations.
        result["instance_id"] = instance_id
        result["cleanup_state"] = "cleanup_unknown"
        if guard is not None and result["state"] not in {"scheduled", "close_requested"}:
            return skill_error("Editor close refused", result.get("reason") or result["state"], native_result=result)
        return skill_success("Editor close state: " + result["state"], native_result=result)
    except Exception:
        # Never echo credentials, input JSON or an exception containing either.
        return skill_error("Editor close unavailable", "Native lifecycle inspection or request failed")


def request_editor_close(
    instance_id: str = "",
    owner: str = "",
    session: str = "",
    host_pid: int = 0,
    creation_filetime: str = "",
    project_file: str = "",
    request_id: str = "",
    expires_unix_ms: str = "",
    proof: str = "",
    **kwargs,
) -> dict:
    try:
        if str(uuid.UUID(instance_id)) != instance_id or str(uuid.UUID(request_id)) != request_id:
            raise ValueError
        if type(host_pid) is not int or not 0 < host_pid <= 4294967295:
            raise ValueError
        if any(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value) is None for value in (owner, session)):
            raise ValueError
        if re.fullmatch(r"[0-9]{1,20}", creation_filetime) is None:
            raise ValueError
        if re.fullmatch(r"[0-9]{13}", expires_unix_ms) is None or re.fullmatch(r"[0-9a-f]{40}", proof) is None:
            raise ValueError
        if not isinstance(project_file, str) or not 0 < len(project_file) <= 4096:
            raise ValueError
        if any(char in project_file for char in "\r\n\x00"):
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        return skill_error("Editor close refused", "Invalid lifecycle guard")
    return _native(
        "request_editor_close_json",
        {
            "instance_id": instance_id,
            "owner": owner,
            "session": session,
            "host_pid": str(host_pid),
            "creation_filetime": creation_filetime,
            "project_file": project_file,
            "request_id": request_id,
            "expires_unix_ms": expires_unix_ms,
            "proof": proof,
        },
    )
