"""Close existing log tabs and focus the active Level Editor viewport."""

from __future__ import annotations

import json

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def focus_level_editor_viewport(**kwargs) -> dict:
    """Use the native Slate bridge to close log tabs and focus the active viewport."""
    import unreal  # noqa: PLC0415

    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    focus = getattr(bridge, "focus_level_editor_viewport", None)
    if not callable(focus):
        return skill_error(
            "Native Level Editor focus bridge unavailable",
            "Install a DCC-MCP Unreal plugin that exposes focus_level_editor_viewport",
        )

    try:
        native_result = json.loads(focus())
    except (TypeError, ValueError) as exc:
        return skill_error("Native Level Editor focus failed", f"invalid result: {exc}")
    if not isinstance(native_result, dict):
        return skill_error("Native Level Editor focus failed", "native result must be an object")

    required_bools = (
        "success",
        "level_editor_activated",
        "viewport_focused",
        "postcondition_met",
    )
    required_lists = ("closed_items", "close_requested_items", "remaining_log_tabs")
    if any(not isinstance(native_result.get(field), bool) for field in required_bools) or any(
        not isinstance(native_result.get(field), list)
        or any(not isinstance(item, str) for item in native_result[field])
        for field in required_lists
    ):
        return skill_error(
            "Native Level Editor focus failed",
            "native result omitted structured focus postconditions",
            native_result=native_result,
        )
    if (
        not native_result.get("success")
        or not native_result["postcondition_met"]
        or not native_result["level_editor_activated"]
        or not native_result["viewport_focused"]
        or native_result["remaining_log_tabs"]
    ):
        return skill_error(
            "Level Editor viewport focus was not verified",
            str(native_result.get("message") or "native focus postcondition was not met"),
            native_result=native_result,
        )

    return skill_success(
        "Focused the active Level Editor viewport",
        closed_items=native_result["closed_items"],
        close_requested_items=native_result["close_requested_items"],
        remaining_log_tabs=native_result["remaining_log_tabs"],
        level_editor_activated=native_result["level_editor_activated"],
        viewport_focused=native_result["viewport_focused"],
        postcondition_met=native_result["postcondition_met"],
        native_result=native_result,
    )
