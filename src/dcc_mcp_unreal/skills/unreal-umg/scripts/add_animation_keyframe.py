"""Add a keyframe to an existing UMG WidgetAnimation track.

Supports keying: position (RenderTransform.Translation), opacity
(RenderOpacity), color (ColorAndOpacity), scale
(RenderTransform.Scale), rotation (RenderTransform.Angle),
visibility, and shear (RenderTransform.Shear).
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

_ANIMATABLE_PROPERTIES = frozenset(
    {
        "position",
        "opacity",
        "color",
        "scale",
        "rotation",
        "visibility",
        "shear",
    }
)

_INTERPOLATION_MODES = frozenset({"Linear", "Cubic", "Constant"})

# UMG widget animations are authored on a 60 fps movie scene display rate.
_UMG_FRAME_RATE = 60

# 2D transform channels keyed per animatable transform property.
_TRANSFORM_CHANNELS = {
    "position": ("Translation.X", "Translation.Y"),
    "scale": ("Scale.X", "Scale.Y"),
    "shear": ("Shear.X", "Shear.Y"),
}

_COLOR_CHANNELS = ("R", "G", "B", "A")


def _validate_asset_path(asset_path: str) -> str | None:
    if not asset_path:
        return "widget_blueprint_path is required"
    if not asset_path.startswith("/Game/"):
        return f"widget_blueprint_path must be under /Game/ namespace, got: {asset_path!r}"
    if ".." in asset_path or "\\" in asset_path:
        return f"widget_blueprint_path contains invalid characters: {asset_path!r}"
    return None


def _validate_property_value(property_name: str, value: object) -> str | None:
    """Return an error message if *value* type doesn't match *property_name*, or None."""
    if property_name == "position":
        if not isinstance(value, dict) or "x" not in value or "y" not in value:
            return "position value must be {x: float, y: float}"
    elif property_name == "opacity":
        if not isinstance(value, (int, float)):
            return "opacity value must be a float between 0.0 and 1.0"
        if not (0.0 <= float(value) <= 1.0):
            return "opacity value must be between 0.0 and 1.0"
    elif property_name == "color":
        if not isinstance(value, dict) or "r" not in value:
            return "color value must be {r: float, g: float, b: float, a: float}"
    elif property_name == "scale":
        if not isinstance(value, dict) or "x" not in value or "y" not in value:
            return "scale value must be {x: float, y: float}"
    elif property_name == "rotation":
        if not isinstance(value, (int, float)):
            return "rotation value must be a float (degrees)"
    elif property_name == "visibility":
        if not isinstance(value, bool):
            return "visibility value must be a boolean"
    elif property_name == "shear":
        if not isinstance(value, dict) or "x" not in value or "y" not in value:
            return "shear value must be {x: float, y: float}"
    return None


@skill_entry
def add_animation_keyframe(
    widget_blueprint_path: str,
    animation_name: str,
    time: float,
    property: str = "opacity",
    value: object = None,
    interpolation: str = "Linear",
    **kwargs: object,
) -> dict:
    """Add a keyframe to a UMG WidgetAnimation."""
    err = _validate_asset_path(widget_blueprint_path)
    if err:
        return skill_error("Invalid asset path", err)

    if property not in _ANIMATABLE_PROPERTIES:
        return skill_error(
            f"Invalid property: {property!r}",
            f"Property must be one of: {', '.join(sorted(_ANIMATABLE_PROPERTIES))}",
        )

    if interpolation not in _INTERPOLATION_MODES:
        return skill_error(
            f"Invalid interpolation: {interpolation!r}",
            f"Interpolation must be one of: {', '.join(sorted(_INTERPOLATION_MODES))}",
        )

    if time < 0:
        return skill_error(
            f"Invalid time: {time}",
            "Keyframe time must be >= 0",
        )

    if value is None:
        return skill_error(
            "Missing keyframe value",
            f"value is required for property '{property}'",
        )

    val_err = _validate_property_value(property, value)
    if val_err:
        return skill_error(f"Invalid value for {property}", val_err)

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

        # Find the animation by name
        animations = widget_tree.get_all_widget_animations()
        animation = None
        for anim in animations:
            if anim.get_name() == animation_name:
                animation = anim
                break

        if animation is None:
            return skill_error(
                f"Animation '{animation_name}' not found",
                f"No animation named '{animation_name}' in {widget_blueprint_path}",
                prompt="Create the animation first with create_umg_animation.",
            )

        # Get the movie scene and add a track
        movie_scene = animation.get_movie_scene()
        if movie_scene is None:
            return skill_error(
                "Movie scene is None",
                "Animation has no movie scene",
            )

        # Determine the track property path based on the property
        track_property_paths = {
            "position": "RenderTransform.Translation",
            "opacity": "RenderOpacity",
            "color": "ColorAndOpacity",
            "scale": "RenderTransform.Scale",
            "rotation": "RenderTransform.Angle",
            "visibility": "Visibility",
            "shear": "RenderTransform.Shear",
        }

        track_path = track_property_paths.get(property, "RenderOpacity")

        # Find or create a float/vector/color track
        binding = movie_scene.find_spawnable_or_possessable(animation_name)
        if binding is None:
            # Create a new binding
            binding = movie_scene.add_spawnable(animation_name)

        # UMG widget animations run on a 60 fps display rate.
        frame = unreal.FrameNumber(int(time * _UMG_FRAME_RATE))

        # Add a transform, color, visibility, or scalar track for the property
        if property in _TRANSFORM_CHANNELS:
            track = binding.add_track(unreal.MovieScene2DTransformTrack)
            if track is not None:
                section = track.add_section()
                section.set_range(time, time)
                channel_x_name, channel_y_name = _TRANSFORM_CHANNELS[property]
                section.find_or_add_channel(channel_x_name).add_key(frame, float(value["x"]))
                section.find_or_add_channel(channel_y_name).add_key(frame, float(value["y"]))
        elif property == "color":
            track = binding.add_track(unreal.MovieSceneColorTrack)
            if track is not None:
                section = track.add_section()
                section.set_range(time, time)
                for channel_name in _COLOR_CHANNELS:
                    component = float(value.get(channel_name.lower(), 1.0))
                    section.find_or_add_channel(channel_name).add_key(frame, component)
        elif property == "visibility":
            track = binding.add_track(unreal.MovieSceneVisibilityTrack)
            if track is not None:
                section = track.add_section()
                section.set_range(time, time)
                section.find_or_add_channel("Visibility").add_key(frame, bool(value))
        else:
            # Float track: opacity, rotation
            track = binding.add_track(unreal.MovieSceneFloatTrack)
            if track is not None:
                section = track.add_section()
                section.set_range(time, time)
                section.find_or_add_channel(track_path).add_key(frame, float(value))

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False):
            return skill_error(
                "Keyframe was added but the Widget Blueprint could not be saved",
                "EditorAssetLibrary.save_loaded_asset returned False",
                prompt="Check that the Widget Blueprint is not read-only or checked out by another user.",
            )

        return skill_success(
            f"Added keyframe at t={time}s for property '{property}' on animation '{animation_name}'",
            prompt="Use add_animation_keyframe for additional keyframes, then compile_widget_blueprint.",
            widget_blueprint_path=widget_blueprint_path,
            animation_name=animation_name,
            time=time,
            property=property,
            interpolation=interpolation,
        )
    except Exception as exc:
        return skill_error(
            f"Failed to add keyframe to animation '{animation_name}'",
            repr(exc),
            prompt="Check Unreal Editor output log for details.",
        )
