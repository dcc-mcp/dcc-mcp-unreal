"""Add a child widget to a CanvasPanel or other panel in a Widget Blueprint.

Supports the full widget type whitelist: Button, TextBlock, Image,
CanvasPanel, VerticalBox, HorizontalBox, Overlay, Border, SizeBox,
EditableText, ProgressBar, Slider.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

_WIDGET_TYPE_WHITELIST = frozenset(
    {
        "Button",
        "TextBlock",
        "Image",
        "CanvasPanel",
        "VerticalBox",
        "HorizontalBox",
        "Overlay",
        "Border",
        "SizeBox",
        "EditableText",
        "ProgressBar",
        "Slider",
    }
)

# Mapping of widget type names to unreal class paths
_WIDGET_CLASS_MAP = {
    "Button": "/Script/UMG.Button",
    "TextBlock": "/Script/UMG.TextBlock",
    "Image": "/Script/UMG.Image",
    "CanvasPanel": "/Script/UMG.CanvasPanel",
    "VerticalBox": "/Script/UMG.VerticalBox",
    "HorizontalBox": "/Script/UMG.HorizontalBox",
    "Overlay": "/Script/UMG.Overlay",
    "Border": "/Script/UMG.Border",
    "SizeBox": "/Script/UMG.SizeBox",
    "EditableText": "/Script/UMG.EditableText",
    "ProgressBar": "/Script/UMG.ProgressBar",
    "Slider": "/Script/UMG.Slider",
}


def _validate_asset_path(asset_path: str) -> str | None:
    if not asset_path:
        return "widget_blueprint_path is required"
    if not asset_path.startswith("/Game/"):
        return f"widget_blueprint_path must be under /Game/ namespace, got: {asset_path!r}"
    if ".." in asset_path or "\\" in asset_path:
        return f"widget_blueprint_path contains invalid characters: {asset_path!r}"
    return None


@skill_entry
def add_widget_to_canvas(
    widget_blueprint_path: str,
    parent_widget_name: str,
    child_widget_type: str,
    child_widget_name: str,
    slot_position: dict | None = None,
    slot_size: dict | None = None,
    **kwargs: object,
) -> dict:
    """Add a child widget to a parent panel in a Widget Blueprint."""
    err = _validate_asset_path(widget_blueprint_path)
    if err:
        return skill_error("Invalid asset path", err)

    if child_widget_type not in _WIDGET_TYPE_WHITELIST:
        return skill_error(
            f"Invalid widget type: {child_widget_type!r}",
            f"Widget type must be one of: {', '.join(sorted(_WIDGET_TYPE_WHITELIST))}",
        )

    if not child_widget_name or not child_widget_name.strip():
        return skill_error("Invalid widget name", "child_widget_name must be a non-empty string")

    if not parent_widget_name or not parent_widget_name.strip():
        return skill_error("Invalid parent name", "parent_widget_name must be a non-empty string")

    try:
        import unreal
    except ImportError:
        return skill_error(
            "Unreal Engine is not available",
            "ImportError: unreal module not found",
        )

    try:
        # Load the Widget Blueprint asset
        blueprint = unreal.load_asset(widget_blueprint_path)
        if blueprint is None:
            return skill_error(
                f"Widget Blueprint not found: {widget_blueprint_path}",
                "Asset could not be loaded",
                prompt="Verify the asset path and that the Widget Blueprint exists.",
            )

        # Get the widget tree from the blueprint
        widget_tree = blueprint.widget_tree
        if widget_tree is None:
            return skill_error(
                "Widget tree is empty",
                f"No widget tree found in {widget_blueprint_path}",
                prompt="Create the Widget Blueprint first with create_widget_blueprint.",
            )

        # Find the parent widget
        parent_widget = widget_tree.find_widget(parent_widget_name)
        if parent_widget is None:
            return skill_error(
                f"Parent widget '{parent_widget_name}' not found",
                f"No widget named '{parent_widget_name}' in {widget_blueprint_path}",
                prompt="Use list_widget_hierarchy to see available widgets.",
            )

        # Create the child widget using the appropriate unreal class
        widget_class_path = _WIDGET_CLASS_MAP[child_widget_type]
        widget_class = unreal.load_class(None, widget_class_path)
        if widget_class is None:
            return skill_error(
                f"Widget class not found: {widget_class_path}",
                f"Could not load {child_widget_type} class",
            )

        child_widget = widget_tree.construct_widget(widget_class, child_widget_name)
        if child_widget is None:
            return skill_error(
                f"Failed to construct widget '{child_widget_name}'",
                f"construct_widget returned None for {child_widget_type}",
            )

        # Add child to parent
        parent_panel = parent_widget
        panel_slot = parent_panel.add_child(child_widget)

        # Configure slot if parent is CanvasPanel
        if panel_slot is not None:
            slot_obj = panel_slot
            if slot_position:
                x = slot_position.get("x", 0.0)
                y = slot_position.get("y", 0.0)
                try:
                    slot_obj.set_position(unreal.Vector2D(x, y))
                except AttributeError:
                    pass  # Slot type may not support position

            if slot_size:
                sx = slot_size.get("x", 200.0)
                sy = slot_size.get("y", 50.0)
                try:
                    slot_obj.set_size(unreal.Vector2D(sx, sy))
                except AttributeError:
                    pass

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False):
            return skill_error(
                "Widget was added but the Widget Blueprint could not be saved",
                "EditorAssetLibrary.save_loaded_asset returned False",
                prompt="Check that the Widget Blueprint is not read-only or checked out by another user.",
            )

        return skill_success(
            f"Added {child_widget_type} '{child_widget_name}' to '{parent_widget_name}'",
            prompt="Use set_widget_properties to configure the new widget, or compile_widget_blueprint to validate.",
            widget_blueprint_path=widget_blueprint_path,
            parent_widget_name=parent_widget_name,
            child_widget_type=child_widget_type,
            child_widget_name=child_widget_name,
        )
    except Exception as exc:
        return skill_error(
            f"Failed to add widget '{child_widget_name}'",
            repr(exc),
            prompt="Check Unreal Editor output log for details.",
        )
