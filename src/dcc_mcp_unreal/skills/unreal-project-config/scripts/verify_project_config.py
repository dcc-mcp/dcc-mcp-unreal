"""Verify renderer values on disk and in the running editor when possible."""

from __future__ import annotations

from typing import List, Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.project_config import (
    ALLOWED_CONSOLE_VARIABLES,
    project_config_path,
    read_console_variables,
    runtime_console_values,
    validate_settings,
)


@skill_entry
def verify_project_config(keys: Optional[List[str]] = None, **kwargs) -> dict:
    try:
        path = project_config_path()
        disk = read_console_variables(path)
        requested = list(keys) if keys is not None else [key for key in disk if key in ALLOWED_CONSOLE_VARIABLES]
        if keys is not None and not requested:
            raise ValueError("Pass one or more allowlisted renderer keys in 'keys'")
        if requested:
            validate_settings({key: disk.get(key, 0) for key in requested})
        runtime = runtime_console_values(requested)
    except (ValueError, OSError) as exc:
        return skill_error("Unable to verify project config", str(exc))

    selected_disk = {key: disk.get(key) for key in requested if key in disk}
    mismatches = {
        key: {"disk": selected_disk[key], "runtime": runtime[key]}
        for key in selected_disk
        if key in runtime and str(selected_disk[key]) != str(runtime[key])
    }
    return skill_success(
        "Project renderer config verified"
        if not mismatches
        else "Project renderer config differs from the running editor",
        prompt="Use the official Unreal MCP SearchCVars tool when runtime_values is unavailable or a restart is pending.",
        config_path=str(path),
        disk_values=selected_disk,
        runtime_values=runtime,
        mismatches=mismatches,
        runtime_query_available=bool(runtime),
        restart_required=bool(mismatches) or not runtime,
    )
