"""Inject controlled input into the PIE viewport.

Uses Unreal Engine's internal input subsystem — no OS-level SendInput,
pyautogui, or similar broad-input APIs. All input is scoped to the active
PIE viewport.
"""

from __future__ import annotations

import time

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_error, unreal_from_exception, unreal_success

_VALID_INPUT_TYPES = {"key_press", "key_release", "key_tap", "mouse_button", "mouse_move", "mouse_scroll"}


def _is_pie_active(unreal) -> bool:
    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    return bool(subsystem and subsystem.is_in_play_in_editor())


def _pie_bridge(unreal):
    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    if bridge is None or not callable(getattr(bridge, "inject_pie_key", None)):
        return None
    return bridge


def _injection_unavailable_error() -> dict:
    return unreal_error(
        "Cannot inject input: no active PIE player is available",
        possible_solutions=["Start a PIE session and wait for its player controller before injecting input."],
    )


def _resolve_key_name(key: str) -> str:
    """Normalize common key names to Unreal Engine key names."""
    key_map = {
        "enter": "Enter",
        "return": "Enter",
        "space": "SpaceBar",
        "spacebar": "SpaceBar",
        "esc": "Escape",
        "escape": "Escape",
        "tab": "Tab",
        "backspace": "BackSpace",
        "delete": "Delete",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "shift": "LeftShift",
        "ctrl": "LeftControl",
        "control": "LeftControl",
        "alt": "LeftAlt",
        "lmb": "LeftMouseButton",
        "rmb": "RightMouseButton",
        "mmb": "MiddleMouseButton",
    }
    return key_map.get(key.lower(), key)


def _inject_key_press(key: str) -> dict:
    """Inject a key press event."""
    import unreal  # noqa: PLC0415

    resolved = _resolve_key_name(key)
    bridge = _pie_bridge(unreal)
    if not _is_pie_active(unreal) or bridge is None or not bridge.inject_pie_key(resolved, True):
        return _injection_unavailable_error()
    return unreal_success(
        "Key press injected: {}".format(resolved),
        key=resolved,
        resolved_from=key if key != resolved else None,
    )


def _inject_key_release(key: str) -> dict:
    """Inject a key release event."""
    import unreal  # noqa: PLC0415

    resolved = _resolve_key_name(key)
    bridge = _pie_bridge(unreal)
    if not _is_pie_active(unreal) or bridge is None or not bridge.inject_pie_key(resolved, False):
        return _injection_unavailable_error()
    return unreal_success(
        "Key release injected: {}".format(resolved),
        key=resolved,
    )


def _inject_key_tap(key: str, duration: float = 0.0) -> dict:
    """Inject a key press and schedule release without blocking the game thread."""
    press_result = _inject_key_press(key)
    if not press_result.get("success"):
        return press_result

    resolved = _resolve_key_name(key)
    hold_seconds = max(0.0, min(float(duration), 5.0))
    if hold_seconds <= 0.0:
        return _inject_key_release(key)

    import dcc_mcp_unreal  # noqa: PLC0415
    import unreal  # noqa: PLC0415

    register_tick = getattr(unreal, "register_slate_post_tick_callback", None)
    unregister_tick = getattr(unreal, "unregister_slate_post_tick_callback", None)
    if not callable(register_tick) or not callable(unregister_tick):
        _inject_key_release(key)
        return unreal_error("Cannot schedule PIE key release: Slate tick callbacks are unavailable")

    release_at = time.monotonic() + hold_seconds
    handle_holder = {}

    def _release_on_tick(_delta_seconds: float = 0.0) -> None:
        if time.monotonic() < release_at:
            return
        try:
            _inject_key_release(resolved)
        finally:
            handle = handle_holder.get("handle")
            if handle is not None:
                unregister_tick(handle)
                pending = getattr(dcc_mcp_unreal, "_pending_pie_input_releases", {})
                pending.pop(handle, None)

    handle = register_tick(_release_on_tick)
    handle_holder["handle"] = handle
    pending = getattr(dcc_mcp_unreal, "_pending_pie_input_releases", None)
    if pending is None:
        pending = {}
        setattr(dcc_mcp_unreal, "_pending_pie_input_releases", pending)
    pending[handle] = _release_on_tick
    return unreal_success(
        "Key tap injected: {}".format(_resolve_key_name(key)),
        key=resolved,
        duration=hold_seconds,
        release_scheduled=True,
    )


def _inject_mouse_button(button: str, position_x=None, position_y=None) -> dict:
    """Inject a mouse button click (press + release)."""
    button_map = {
        "left": "LeftMouseButton",
        "right": "RightMouseButton",
        "middle": "MiddleMouseButton",
        "thumb": "ThumbMouseButton",
        "thumb2": "ThumbMouseButton2",
    }
    resolved = button_map.get(button, button)
    if position_x is None and position_y is None:
        return _inject_key_tap(resolved, duration=0.05)
    if position_x is None or position_y is None:
        return unreal_error("position_x and position_y must be provided together for a positioned PIE click")
    try:
        normalized_x = float(position_x)
        normalized_y = float(position_y)
    except (TypeError, ValueError):
        return unreal_error("position_x and position_y must be numbers between 0.0 and 1.0")
    if not (0.0 <= normalized_x <= 1.0 and 0.0 <= normalized_y <= 1.0):
        return unreal_error("position_x and position_y must be between 0.0 and 1.0")

    import unreal  # noqa: PLC0415

    bridge = _pie_bridge(unreal)
    click_pointer = getattr(bridge, "click_pie_pointer_button", None) if bridge is not None else None
    if not _is_pie_active(unreal) or not callable(click_pointer):
        return _injection_unavailable_error()
    if not click_pointer(resolved, normalized_x, normalized_y):
        return unreal_error("The positioned PIE mouse click was not handled by the active Slate window")
    return unreal_success(
        "Mouse button clicked at normalized PIE window position",
        button=resolved,
        position_x=normalized_x,
        position_y=normalized_y,
    )


def _inject_mouse_move(delta_x: float, delta_y: float) -> dict:
    """Inject deterministic look input into the possessed PIE controller."""
    import unreal  # noqa: PLC0415

    bridge = _pie_bridge(unreal)
    inject_look = getattr(bridge, "inject_pie_look", None) if bridge is not None else None
    if not _is_pie_active(unreal) or not callable(inject_look):
        return _injection_unavailable_error()
    if not inject_look(float(delta_x), float(delta_y)):
        return _injection_unavailable_error()
    return unreal_success(
        "PIE look input injected",
        delta_x=delta_x,
        delta_y=delta_y,
    )


def _inject_mouse_scroll(scroll_delta: float) -> dict:
    """Inject mouse scroll wheel delta."""
    import unreal  # noqa: PLC0415

    bridge = _pie_bridge(unreal)
    if (
        not _is_pie_active(unreal)
        or bridge is None
        or not bridge.inject_pie_axis("MouseWheelAxis", float(scroll_delta))
    ):
        return _injection_unavailable_error()
    return unreal_success(
        "Mouse scroll injected",
        scroll_delta=scroll_delta,
    )


_INPUT_HANDLERS = {
    "key_press": _inject_key_press,
    "key_release": _inject_key_release,
    "key_tap": _inject_key_tap,
    "mouse_button": _inject_mouse_button,
    "mouse_move": _inject_mouse_move,
    "mouse_scroll": _inject_mouse_scroll,
}


@skill_entry
def pie_inject_input(
    input_type: str = "",
    key: str = "",
    button: str = "left",
    delta_x: float = 0.0,
    delta_y: float = 0.0,
    scroll_delta: float = 0.0,
    duration: float = 0.0,
    position_x=None,
    position_y=None,
    **kwargs,
) -> dict:
    """Inject controlled input into the active PIE viewport.

    Args:
        input_type: Type of input (key_press, key_release, key_tap, mouse_button, mouse_move, mouse_scroll).
        key: Key name for keyboard/mouse button events.
        button: Mouse button name (left, right, middle, thumb, thumb2).
        delta_x: Horizontal mouse movement.
        delta_y: Vertical mouse movement.
        scroll_delta: Scroll wheel delta.
        duration: Hold duration for key_tap in seconds.
        position_x: Optional normalized active-window X coordinate for mouse_button.
        position_y: Optional normalized active-window Y coordinate for mouse_button.
    """
    if not input_type or not str(input_type).strip():
        return missing_param_error("input_type")

    input_type = str(input_type).strip().lower()
    if input_type not in _VALID_INPUT_TYPES:
        return unreal_error(
            "Invalid input_type: '{}'".format(input_type),
            "Must be one of: {}".format(", ".join(sorted(_VALID_INPUT_TYPES))),
            possible_solutions=["Pass a valid input_type."],
        )

    try:
        handler = _INPUT_HANDLERS.get(input_type)
        if handler is None:
            return unreal_error("No handler for input_type '{}'".format(input_type))

        # Dispatch based on type
        if input_type in ("key_press", "key_release"):
            if not key:
                return missing_param_error("key")
            return handler(key)
        elif input_type == "key_tap":
            if not key:
                return missing_param_error("key")
            return handler(key, duration)
        elif input_type == "mouse_button":
            return handler(button, position_x, position_y)
        elif input_type == "mouse_move":
            return handler(delta_x, delta_y)
        elif input_type == "mouse_scroll":
            return handler(scroll_delta)
        else:
            return unreal_error("Unhandled input_type: '{}'".format(input_type))
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to inject input of type '{}'".format(input_type))
