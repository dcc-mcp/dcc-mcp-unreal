"""Inspect allowlisted renderer project settings."""

from __future__ import annotations

from typing import List, Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.project_config import (
    ALLOWED_CONSOLE_VARIABLES,
    project_config_path,
    read_console_variables,
    validate_settings,
)


@skill_entry
def inspect_project_config(keys: Optional[List[str]] = None, **kwargs) -> dict:
    try:
        path = project_config_path()
        values = read_console_variables(path)
        requested = list(keys or values.keys())
        validate_settings({key: values.get(key, 0) for key in requested})
    except (ValueError, OSError) as exc:
        return skill_error("Unable to inspect project config", str(exc))

    return skill_success(
        f"Inspected {len(requested)} renderer setting(s)",
        prompt="Use apply_project_config for an allowlisted patch, then verify after restart.",
        config_path=str(path),
        section="[ConsoleVariables]",
        values={key: values.get(key) for key in requested if key in ALLOWED_CONSOLE_VARIABLES},
        missing=[key for key in requested if key not in values],
        restart_required=False,
    )
