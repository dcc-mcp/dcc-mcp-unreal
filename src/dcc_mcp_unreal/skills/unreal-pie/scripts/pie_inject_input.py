"""Inject controlled input into the PIE viewport.

Uses Unreal Engine's internal input subsystem — no OS-level SendInput,
pyautogui, or similar broad-input APIs. All input is scoped to the active
PIE viewport.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import missing_param_error, unreal_error, unreal_from_exception, unreal_success

_VALID_INPUT_TYPES = {"key_press", "key_release", "key_tap", "mouse_button", "mouse_move", "mouse_scroll"}


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
    # Use the InputProcessor subsystem
    input_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if input_subsystem is not None:
        # Use console command - the most reliable cross-version path
        cmd = "InputKey {}".format(resolved)
        unreal.SystemLibrary.execute_console_command(
            unreal.EditorLevelLibrary.get_editor_world(),
            cmd,
        )
        return unreal_success(
            "Key press injected: {}".format(resolved),
            key=resolved,
            resolved_from=key if key != resolved else None,
        )

    return unreal_error(
        "Cannot inject input: no input subsystem available",
        possible_solutions=["Ensure a PIE session is active."],
    )


def _inject_key_release(key: str) -> dict:
    """Inject a key release event."""
    import unreal  # noqa: PLC0415

    resolved = _resolve_key_name(key)
    cmd = "InputKey {} Release".format(resolved)
    unreal.SystemLibrary.execute_console_command(
        unreal.EditorLevelLibrary.get_editor_world(),
        cmd,
    )
    return unreal_success(
        "Key release injected: {}".format(resolved),
        key=resolved,
    )


def _inject_key_tap(key: str, duration: float = 0.0) -> dict:
    """Inject a key press followed by release."""
    _inject_key_press(key)
    if duration > 0:
        import time

        time.sleep(min(duration, 5.0))
    _inject_key_release(key)
    return unreal_success(
        "Key tap injected: {}".format(_resolve_key_name(key)),
        key=_resolve_key_name(key),
        duration=duration,
    )


def _inject_mouse_button(button: str) -> dict:
    """Inject a mouse button click (press + release)."""
    button_map = {
        "left": "LeftMouseButton",
        "right": "RightMouseButton",
        "middle": "MiddleMouseButton",
        "thumb": "ThumbMouseButton",
        "thumb2": "ThumbMouseButton2",
    }
    resolved = button_map.get(button, button)
    return _inject_key_tap(resolved, duration=0.05)


def _inject_mouse_move(delta_x: float, delta_y: float) -> dict:
    """Inject mouse movement delta."""
    import unreal  # noqa: PLC0415

    # Use console command for mouse move — the most portable approach
    world = unreal.EditorLevelLibrary.get_editor_world()
    cmd = "SlateDebugger.MouseMove {} {}".format(int(delta_x), int(delta_y))
    unreal.SystemLibrary.execute_console_command(world, cmd)
    return unreal_success(
        "Mouse move injected",
        delta_x=delta_x,
        delta_y=delta_y,
    )


def _inject_mouse_scroll(scroll_delta: float) -> dict:
    """Inject mouse scroll wheel delta."""
    import unreal  # noqa: PLC0415

    world = unreal.EditorLevelLibrary.get_editor_world()
    cmd = "SlateDebugger.MouseScroll {}".format(int(scroll_delta))
    unreal.SystemLibrary.execute_console_command(world, cmd)
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
            return handler(button)
        elif input_type == "mouse_move":
            return handler(delta_x, delta_y)
        elif input_type == "mouse_scroll":
            return handler(scroll_delta)
        else:
            return unreal_error("Unhandled input_type: '{}'".format(input_type))
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to inject input of type '{}'".format(input_type))
