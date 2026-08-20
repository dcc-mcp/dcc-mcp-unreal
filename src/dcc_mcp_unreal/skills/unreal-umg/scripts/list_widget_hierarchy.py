"""List the widget tree hierarchy of a Widget Blueprint.

Read-only inspection tool that returns the full widget tree:
widget type, name, parent, and children for each widget.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _validate_asset_path(asset_path: str) -> str | None:
    if not asset_path:
        return "widget_blueprint_path is required"
    if not asset_path.startswith("/Game/"):
        return f"widget_blueprint_path must be under /Game/ namespace, got: {asset_path!r}"
    if ".." in asset_path or "\\" in asset_path:
        return f"widget_blueprint_path contains invalid characters: {asset_path!r}"
    return None


def _traverse_widget_tree(widget: object, max_depth: int, current_depth: int = 0) -> list[dict]:
    """Recursively traverse the widget tree, respecting *max_depth*."""
    if current_depth > max_depth or widget is None:
        return []

    result = []
    widget_info = {
        "name": str(widget.get_name()) if hasattr(widget, "get_name") else "Unknown",
        "type": str(widget.get_class().get_name()) if hasattr(widget, "get_class") else "Unknown",
        "depth": current_depth,
    }

    # Check visibility/state
    try:
        widget_info["is_visible"] = widget.is_visible()
    except Exception:
        widget_info["is_visible"] = True

    # Check for slot info
    try:
        slot = widget.slot
        if slot:
            widget_info["has_slot"] = True
    except Exception:
        widget_info["has_slot"] = False

    result.append(widget_info)

    # Recurse into children
    if current_depth < max_depth:
        children = []
        try:
            # Get child count and iterate
            child_count = widget.get_children_count()
            for i in range(child_count):
                child = widget.get_child_at(i)
                if child:
                    children.append(str(child.get_name()) if hasattr(child, "get_name") else f"Child_{i}")
                    result.extend(_traverse_widget_tree(child, max_depth, current_depth + 1))
        except Exception:
            pass
        widget_info["children"] = children

    return result


@skill_entry
def list_widget_hierarchy(
    widget_blueprint_path: str,
    root_widget_name: str | None = None,
    max_depth: int = 10,
    **kwargs: object,
) -> dict:
    """List the full widget tree hierarchy of a Widget Blueprint."""
    err = _validate_asset_path(widget_blueprint_path)
    if err:
        return skill_error("Invalid asset path", err)

    if max_depth < 1:
        return skill_error(
            f"Invalid max_depth: {max_depth}",
            "max_depth must be >= 1",
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

        # Determine root widget
        if root_widget_name:
            root_widget = widget_tree.find_widget(root_widget_name)
            if root_widget is None:
                return skill_error(
                    f"Widget '{root_widget_name}' not found",
                    f"No widget named '{root_widget_name}' in {widget_blueprint_path}",
                )
        else:
            root_widget = widget_tree.root_widget
            if root_widget is None:
                return skill_error(
                    "No root widget found",
                    "The Widget Blueprint has no root widget.",
                )
            root_widget_name = str(root_widget.get_name()) if hasattr(root_widget, "get_name") else "Root"

        hierarchy = _traverse_widget_tree(root_widget, max_depth)

        total_widgets = len(hierarchy)
        max_reached = total_widgets > 0 and hierarchy[-1].get("depth", 0) >= max_depth

        return skill_success(
            f"Widget hierarchy listed: {total_widgets} widget(s) from root '{root_widget_name}'",
            prompt="Use set_widget_properties or bind_widget_event on a widget from this hierarchy."
            if not max_reached
            else f"Max depth {max_depth} reached; increase max_depth to see more levels.",
            widget_blueprint_path=widget_blueprint_path,
            root_widget_name=root_widget_name,
            total_widgets=total_widgets,
            max_depth_reached=max_reached,
            hierarchy=hierarchy,
        )
    except Exception as exc:
        return skill_error(
            f"Failed to list widget hierarchy for '{widget_blueprint_path}'",
            repr(exc),
            prompt="Check Unreal Editor output log for details.",
        )
