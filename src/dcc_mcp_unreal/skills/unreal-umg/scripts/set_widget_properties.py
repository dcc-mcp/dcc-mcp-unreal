"""Set UMG widget display properties: size, anchors, visibility, tooltip, style.

Modifies an existing widget's properties inside a Widget Blueprint.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

_ANCHOR_PRESETS = frozenset(
    {
        "top-left",
        "top-center",
        "top-right",
        "center-left",
        "center-center",
        "center-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
        "stretch",
        "stretch-top",
        "stretch-middle",
        "stretch-bottom",
    }
)

_VISIBILITY_MODES = frozenset(
    {
        "Visible",
        "Collapsed",
        "Hidden",
        "HitTestInvisible",
        "SelfHitTestInvisible",
    }
)

_ANCHOR_PRESET_VALUES: dict[str, dict[str, float]] = {
    "top-left": {"min_x": 0.0, "min_y": 0.0, "max_x": 0.0, "max_y": 0.0},
    "top-center": {"min_x": 0.5, "min_y": 0.0, "max_x": 0.5, "max_y": 0.0},
    "top-right": {"min_x": 1.0, "min_y": 0.0, "max_x": 1.0, "max_y": 0.0},
    "center-left": {"min_x": 0.0, "min_y": 0.5, "max_x": 0.0, "max_y": 0.5},
    "center-center": {"min_x": 0.5, "min_y": 0.5, "max_x": 0.5, "max_y": 0.5},
    "center-right": {"min_x": 1.0, "min_y": 0.5, "max_x": 1.0, "max_y": 0.5},
    "bottom-left": {"min_x": 0.0, "min_y": 1.0, "max_x": 0.0, "max_y": 1.0},
    "bottom-center": {"min_x": 0.5, "min_y": 1.0, "max_x": 0.5, "max_y": 1.0},
    "bottom-right": {"min_x": 1.0, "min_y": 1.0, "max_x": 1.0, "max_y": 1.0},
    "stretch": {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0},
    "stretch-top": {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 0.0},
    "stretch-middle": {"min_x": 0.0, "min_y": 0.5, "max_x": 1.0, "max_y": 0.5},
    "stretch-bottom": {"min_x": 0.0, "min_y": 1.0, "max_x": 1.0, "max_y": 1.0},
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
def set_widget_properties(
    widget_blueprint_path: str,
    widget_name: str,
    size: dict | None = None,
    anchors: dict | None = None,
    visibility: str | None = None,
    tooltip: str | None = None,
    is_enabled: bool | None = None,
    render_opacity: float | None = None,
    z_order: int | None = None,
    **kwargs: object,
) -> dict:
    """Set display properties on a UMG widget."""
    err = _validate_asset_path(widget_blueprint_path)
    if err:
        return skill_error("Invalid asset path", err)

    if not widget_name or not widget_name.strip():
        return skill_error("Invalid widget name", "widget_name must be a non-empty string")

    if visibility is not None and visibility not in _VISIBILITY_MODES:
        return skill_error(
            f"Invalid visibility: {visibility!r}",
            f"Must be one of: {', '.join(sorted(_VISIBILITY_MODES))}",
        )

    if anchors is not None:
        preset = anchors.get("preset")
        if preset is not None and preset not in _ANCHOR_PRESETS:
            return skill_error(
                f"Invalid anchor preset: {preset!r}",
                f"Must be one of: {', '.join(sorted(_ANCHOR_PRESETS))}",
            )

    if render_opacity is not None and not (0.0 <= render_opacity <= 1.0):
        return skill_error(
            f"Invalid render_opacity: {render_opacity}",
            "render_opacity must be between 0.0 and 1.0",
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

        changed = []

        # Size override
        if size is not None:
            sx = size.get("x")
            sy = size.get("y")
            if sx is not None or sy is not None:
                try:
                    slot = widget.slot
                    if slot and hasattr(slot, "set_size"):
                        slot.set_size(
                            unreal.Vector2D(
                                sx if sx is not None else 0,
                                sy if sy is not None else 0,
                            )
                        )
                        changed.append(f"size=({sx}, {sy})")
                except Exception:
                    pass

        # Anchors
        if anchors is not None:
            preset = anchors.get("preset")
            if preset is not None:
                anchor_vals = _ANCHOR_PRESET_VALUES[preset]
                min_x = anchor_vals["min_x"]
                min_y = anchor_vals["min_y"]
                max_x = anchor_vals["max_x"]
                max_y = anchor_vals["max_y"]
            else:
                min_x = anchors.get("minimum_x", 0.0)
                min_y = anchors.get("minimum_y", 0.0)
                max_x = anchors.get("maximum_x", 1.0)
                max_y = anchors.get("maximum_y", 1.0)

            try:
                slot = widget.slot
                if slot and hasattr(slot, "set_anchors"):
                    slot.set_anchors(unreal.Anchors(min_x, min_y, max_x, max_y))
                    changed.append(f"anchors=({min_x},{min_y},{max_x},{max_y})")
            except Exception:
                pass

        # Visibility
        if visibility is not None:
            try:
                vis_enum = getattr(unreal.SlateVisibility, visibility)
                widget.set_visibility(vis_enum)
                changed.append(f"visibility={visibility}")
            except Exception:
                pass

        # Tooltip
        if tooltip is not None:
            widget.set_tool_tip_text(tooltip)
            changed.append(f"tooltip='{tooltip}'")

        # Enabled state
        if is_enabled is not None:
            widget.set_is_enabled(is_enabled)
            changed.append(f"enabled={is_enabled}")

        # Render opacity
        if render_opacity is not None:
            widget.set_render_opacity(render_opacity)
            changed.append(f"render_opacity={render_opacity}")

        # Z-order
        if z_order is not None:
            widget.set_z_order(z_order)
            changed.append(f"z_order={z_order}")

        if not changed:
            return skill_success(
                f"No properties changed for widget '{widget_name}'",
                prompt="No property values were provided; widget is unchanged.",
                widget_name=widget_name,
                widget_blueprint_path=widget_blueprint_path,
            )

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False):
            return skill_error(
                "Properties were set but the Widget Blueprint could not be saved",
                "EditorAssetLibrary.save_loaded_asset returned False",
                prompt="Check that the Widget Blueprint is not read-only or checked out by another user.",
            )

        return skill_success(
            f"Updated properties on '{widget_name}': {', '.join(changed)}",
            prompt="Use compile_widget_blueprint to verify the changes.",
            widget_name=widget_name,
            widget_blueprint_path=widget_blueprint_path,
            changed_properties=changed,
        )
    except Exception as exc:
        return skill_error(
            f"Failed to set properties on widget '{widget_name}'",
            repr(exc),
            prompt="Check Unreal Editor output log for details.",
        )
