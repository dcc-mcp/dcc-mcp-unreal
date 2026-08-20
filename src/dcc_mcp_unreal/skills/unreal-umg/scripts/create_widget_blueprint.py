"""Create a UMG Widget Blueprint asset in Unreal Engine.

Creates a new Widget Blueprint inheriting from UserWidget (or an optional
parent class) at the specified /Game/ path.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

# Widget type whitelist — shared across all UMG tools
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


def _validate_asset_path(asset_path: str) -> str | None:
    """Return an error message if *asset_path* is invalid, or None if valid."""
    if not asset_path:
        return "asset_path is required"
    if not asset_path.startswith("/Game/"):
        return f"asset_path must be under /Game/ namespace, got: {asset_path!r}"
    if ".." in asset_path:
        return f"asset_path must not contain '..': {asset_path!r}"
    if "\\" in asset_path:
        return f"asset_path must use forward slashes, got: {asset_path!r}"
    return None


@skill_entry
def create_widget_blueprint(
    asset_path: str,
    widget_name: str,
    parent_class: str = "/Script/UMG.UserWidget",
    **kwargs: object,
) -> dict:
    """Create a new UMG Widget Blueprint asset."""
    err = _validate_asset_path(asset_path)
    if err:
        return skill_error("Invalid asset path", err)

    if not widget_name or not widget_name.strip():
        return skill_error("Invalid widget name", "widget_name must be a non-empty string")

    try:
        import unreal
    except ImportError:
        return skill_error(
            "Unreal Engine is not available",
            "ImportError: unreal module not found",
            prompt="Ensure the script is running inside Unreal Editor with Python support enabled.",
        )

    try:
        factory = unreal.WidgetBlueprintFactory()
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        full_path = f"{asset_path.rstrip('/')}/{widget_name}"

        blueprint = asset_tools.create_asset(
            asset_name=widget_name,
            package_path=asset_path.rstrip("/"),
            asset_class=unreal.WidgetBlueprint,
            factory=factory,
        )

        if blueprint is None:
            return skill_error(
                f"Failed to create Widget Blueprint '{widget_name}'",
                f"Asset creation returned None for path {full_path}",
                prompt="Check that the path exists and the asset name is not already in use.",
            )

        # Set parent class if not default
        if parent_class != "/Script/UMG.UserWidget":
            parent_cls = unreal.load_class(None, parent_class)
            if parent_cls is not None:
                blueprint.set_editor_property("parent_class", parent_cls)

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False):
            return skill_error(
                f"Widget Blueprint '{widget_name}' was created but could not be saved",
                "EditorAssetLibrary.save_loaded_asset returned False",
                prompt="Check that the target content folder is writable.",
            )

        return skill_success(
            f"Created Widget Blueprint '{widget_name}' at {full_path}",
            prompt="Use add_widget_to_canvas to add widgets to the new blueprint.",
            asset_path=full_path,
            widget_name=widget_name,
            parent_class=parent_class,
        )
    except Exception as exc:
        return skill_error(
            f"Failed to create Widget Blueprint '{widget_name}'",
            repr(exc),
            prompt="Check the Unreal Editor output log for details.",
        )
