"""Create a UMG WidgetAnimation track on a widget in a Widget Blueprint.

Creates a named animation timeline that can receive keyframes for
position, opacity, color, scale, rotation, visibility, or shear.
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


@skill_entry
def create_umg_animation(
    widget_blueprint_path: str,
    animation_name: str,
    target_widget_name: str,
    duration: float = 1.0,
    loop: bool = False,
    num_loops_to_play: int = 1,
    **kwargs: object,
) -> dict:
    """Create a new WidgetAnimation on a UMG widget."""
    err = _validate_asset_path(widget_blueprint_path)
    if err:
        return skill_error("Invalid asset path", err)

    if not animation_name or not animation_name.strip():
        return skill_error("Invalid animation name", "animation_name must be a non-empty string")

    if not target_widget_name or not target_widget_name.strip():
        return skill_error("Invalid widget name", "target_widget_name must be a non-empty string")

    if duration <= 0:
        return skill_error(
            f"Invalid duration: {duration}",
            "duration must be a positive number in seconds",
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

        target_widget = widget_tree.find_widget(target_widget_name)
        if target_widget is None:
            return skill_error(
                f"Widget '{target_widget_name}' not found",
                f"No widget named '{target_widget_name}' in {widget_blueprint_path}",
            )

        # Create the animation
        animation = widget_tree.create_widget_animation(target_widget, animation_name)
        if animation is None:
            return skill_error(
                f"Failed to create animation '{animation_name}'",
                "create_widget_animation returned None",
                prompt="Check that no animation with this name already exists.",
            )

        # Set animation properties
        try:
            animation.set_editor_property("movie_scene", animation.get_movie_scene())
        except Exception:
            pass

        # Set playback properties
        blueprint.set_editor_property("num_loops_to_play", num_loops_to_play if loop else 1)

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False):
            return skill_error(
                "Animation was created but the Widget Blueprint could not be saved",
                "EditorAssetLibrary.save_loaded_asset returned False",
                prompt="Check that the Widget Blueprint is not read-only or checked out by another user.",
            )

        return skill_success(
            f"Created animation '{animation_name}' on widget '{target_widget_name}'",
            prompt="Use add_animation_keyframe to add keyframes to this animation.",
            widget_blueprint_path=widget_blueprint_path,
            animation_name=animation_name,
            target_widget_name=target_widget_name,
            duration=duration,
            loop=loop,
        )
    except Exception as exc:
        return skill_error(
            f"Failed to create animation '{animation_name}'",
            repr(exc),
            prompt="Check Unreal Editor output log for details.",
        )
