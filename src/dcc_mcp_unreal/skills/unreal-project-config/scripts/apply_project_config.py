"""Apply allowlisted renderer settings to the active Unreal project."""

from __future__ import annotations

from typing import Dict, Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.project_config import PRESETS, patch_console_variables, project_config_path, validate_settings


@skill_entry
def apply_project_config(
    settings: Optional[Dict[str, float]] = None,
    preset: str = "",
    **kwargs,
) -> dict:
    if settings is not None and not isinstance(settings, dict):
        return skill_error("Invalid settings", "settings must be an object")
    if preset and preset not in PRESETS:
        return skill_error("Unknown renderer preset", f"Supported presets: {', '.join(sorted(PRESETS))}")
    merged = dict(PRESETS.get(preset, {}))
    merged.update(dict(settings or {}))
    try:
        normalized = validate_settings(merged)
        path = project_config_path()
        result = patch_console_variables(path, normalized)
    except (ValueError, OSError) as exc:
        return skill_error("Unable to apply project config", str(exc))

    changed = result["changed"]
    return skill_success(
        "Project renderer config updated" if changed else "Project renderer config already matches",
        prompt="Restart Unreal if needed, then run verify_project_config and the official CVar/log checks.",
        config_path=str(path),
        applied=changed,
        values=result["values"],
        backup_path=str(path.with_suffix(path.suffix + ".bak")) if changed else None,
        restart_required=bool(changed),
        preset=preset or None,
    )
