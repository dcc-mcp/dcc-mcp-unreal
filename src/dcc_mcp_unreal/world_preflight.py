"""Read-only editor-world readiness diagnostics for Unreal tools."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple


def _subsystem_flag(unreal_module: Any, class_name: str, method_name: str) -> bool:
    subsystem_class = getattr(unreal_module, class_name, None)
    get_subsystem = getattr(unreal_module, "get_editor_subsystem", None)
    if subsystem_class is None or not callable(get_subsystem):
        return False
    try:
        subsystem = get_subsystem(subsystem_class)
        method = getattr(subsystem, method_name, None)
        return bool(method()) if callable(method) else False
    except Exception:
        return False


def inspect_editor_world(unreal_module: Any) -> Tuple[Any, Dict[str, bool]]:
    """Return the editor world and read-only PIE/MRQ state flags."""
    world = unreal_module.EditorLevelLibrary.get_editor_world()
    if world is not None:
        return world, {"pie_active": False, "mrq_active": False}
    return world, {
        "pie_active": _subsystem_flag(unreal_module, "LevelEditorSubsystem", "is_in_play_in_editor"),
        "mrq_active": _subsystem_flag(unreal_module, "MoviePipelineQueueSubsystem", "is_rendering"),
    }


def editor_world_error(
    unreal_module: Any,
    *,
    retry_tool: str,
    retry_arguments: Mapping[str, Any] | None = None,
) -> Tuple[Any, Dict[str, Any] | None]:
    """Return an editor world or an actionable ActionResult error."""
    from dcc_mcp_core.skill import skill_error  # noqa: PLC0415

    world, state = inspect_editor_world(unreal_module)
    if world is not None:
        return world, None

    retry_args = dict(retry_arguments or {})
    if state["pie_active"] or state["mrq_active"]:
        if state["mrq_active"]:
            next_action: Dict[str, Any] = {
                "action": "poll_then_retry",
                "poll_tool": "unreal_cinematics__get_render_status",
                "poll_until": {"is_rendering": False},
                "retry_tool": retry_tool,
                "retry_arguments": retry_args,
            }
        else:
            next_action = {
                "action": "poll_then_retry",
                "poll_tool": "unreal_pie__pie_get_status",
                "poll_until": {"state": "stopped"},
                "retry_tool": retry_tool,
                "retry_arguments": retry_args,
            }
        return None, skill_error(
            "Editor world is temporarily unavailable",
            "A PIE or Movie Render Queue world is active",
            reason="pie_or_mrq_active",
            next_action=next_action,
            **state,
        )

    return None, skill_error(
        "Editor world is not loaded",
        "EditorLevelLibrary.get_editor_world() returned None",
        reason="editor_not_loaded",
        next_action={
            "action": "retry_when_editor_loaded",
            "retry_tool": retry_tool,
            "retry_arguments": retry_args,
        },
        **state,
    )
