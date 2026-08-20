"""Bind a UMG widget interaction event to a Blueprint function.

Supported events: OnClicked, OnPressed, OnReleased, OnHovered,
OnUnhovered, OnDragDetected, OnDragCancelled. Event names are
validated against a whitelist.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

_EVENT_WHITELIST = frozenset(
    {
        "OnClicked",
        "OnPressed",
        "OnReleased",
        "OnHovered",
        "OnUnhovered",
        "OnDragDetected",
        "OnDragCancelled",
    }
)

# Map event names to their delegate property name on UMG widgets
_EVENT_DELEGATE_MAP: dict[str, str] = {
    "OnClicked": "on_clicked",
    "OnPressed": "on_pressed",
    "OnReleased": "on_released",
    "OnHovered": "on_hovered",
    "OnUnhovered": "on_unhovered",
    "OnDragDetected": "on_drag_detected",
    "OnDragCancelled": "on_drag_cancelled",
}


def _validate_asset_path(asset_path: str) -> str | None:
    if not asset_path:
        return "widget_blueprint_path is required"
    if not asset_path.startswith("/Game/"):
        return f"widget_blueprint_path must be under /Game/ namespace, got: {asset_path!r}"
    if ".." in asset_path or "\\" in asset_path:
        return f"widget_blueprint_path contains invalid characters: {asset_path!r}"
    return None


def _is_valid_function_name(name: str) -> bool:
    """Check that *name* is a valid identifier for a Blueprint function."""
    if not name or not name[0].isalpha():
        return False
    return all(c.isalnum() or c == "_" for c in name)


@skill_entry
def bind_widget_event(
    widget_blueprint_path: str,
    widget_name: str,
    event_name: str,
    function_name: str,
    create_function: bool = True,
    **kwargs: object,
) -> dict:
    """Bind a widget event to a Blueprint function."""
    err = _validate_asset_path(widget_blueprint_path)
    if err:
        return skill_error("Invalid asset path", err)

    if event_name not in _EVENT_WHITELIST:
        return skill_error(
            f"Invalid event name: {event_name!r}",
            f"Event must be one of: {', '.join(sorted(_EVENT_WHITELIST))}",
        )

    if not widget_name or not widget_name.strip():
        return skill_error("Invalid widget name", "widget_name must be a non-empty string")

    if not function_name or not _is_valid_function_name(function_name):
        return skill_error(
            f"Invalid function name: {function_name!r}",
            "function_name must be a valid Python/Blueprint identifier",
        )

    try:
        import unreal
    except ImportError:
        return skill_error("Unreal Engine is not available", "ImportError: unreal module not found")

    try:
        blueprint = unreal.load_asset(widget_blueprint_path)
        if blueprint is None:
            return skill_error(
                f"Widget Blueprint not found: {widget_blueprint_path}",
                "Asset could not be loaded",
            )

        widget_tree = blueprint.widget_tree
        if widget_tree is None:
            return skill_error(
                "Widget tree is empty",
                f"No widget tree found in {widget_blueprint_path}",
            )

        widget = widget_tree.find_widget(widget_name)
        if widget is None:
            return skill_error(
                f"Widget '{widget_name}' not found",
                f"No widget named '{widget_name}' in {widget_blueprint_path}",
            )

        # Get the Blueprint generated class
        bp_class = blueprint.generated_class()
        if bp_class is None:
            return skill_error(
                "Blueprint not compiled",
                f"No generated class for {widget_blueprint_path}",
                prompt="Compile the Widget Blueprint first with compile_widget_blueprint.",
            )

        # Try to find or create the function in the Blueprint
        delegate_prop = _EVENT_DELEGATE_MAP.get(event_name)
        if delegate_prop is None:
            return skill_error(
                f"Unknown delegate mapping for event: {event_name}",
                f"No delegate property mapping for {event_name}",
            )

        # Check if function exists in the class
        function_graph = None
        if create_function:
            # Add function graph to the blueprint
            try:
                function_graph = unreal.BlueprintEditorLibrary.add_function_graph(blueprint, function_name)
            except Exception:
                function_graph = None

        # Bind the delegate
        try:
            delegate = widget.get_editor_property(delegate_prop)
            if delegate is not None:
                # Use the UMG editor binding API
                widget.bind_event(delegate, unreal.Name(function_name))
            else:
                # Try direct property bind
                unreal.WidgetBlueprintLibrary.bind_event(widget, event_name, unreal.Name(function_name))
        except Exception as bind_exc:
            return skill_error(
                f"Failed to bind event {event_name} on '{widget_name}'",
                repr(bind_exc),
                prompt="Check that the widget supports this event type.",
            )

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False):
            return skill_error(
                "Event was bound but the Widget Blueprint could not be saved",
                "EditorAssetLibrary.save_loaded_asset returned False",
                prompt="Check that the Widget Blueprint is not read-only or checked out by another user.",
            )

        return skill_success(
            f"Bound {event_name} on '{widget_name}' to function '{function_name}'",
            prompt="Use compile_widget_blueprint to verify the binding compiles.",
            widget_name=widget_name,
            widget_blueprint_path=widget_blueprint_path,
            event_name=event_name,
            function_name=function_name,
            function_created=function_graph is not None if create_function else False,
        )
    except Exception as exc:
        return skill_error(
            f"Failed to bind event {event_name} on '{widget_name}'",
            repr(exc),
            prompt="Check Unreal Editor output log for details.",
        )
