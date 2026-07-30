"""Create or update a persistent OpenColorIO configuration asset."""

from __future__ import annotations

from pathlib import Path

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def create_ocio_configuration(
    asset_path: str = "",
    configuration_path: str = "ocio://default",
    source_color_space: str = "ACEScg",
    display: str = "Rec.1886 Rec.709 - Display",
    view: str = "ACES 1.0 - SDR Video",
    apply_to_active_viewport: bool = False,
    **kwargs,
) -> dict:
    """Create a saved OCIO asset and verify the requested display transform."""
    import unreal  # noqa: PLC0415

    asset_path = asset_path.rstrip("/")
    if not asset_path.startswith("/Game/") or not asset_path[6:]:
        return skill_error("Invalid asset_path", "asset_path must identify an asset under /Game")
    if not all(value.strip() for value in (configuration_path, source_color_space, display, view)):
        return skill_error("Invalid OCIO settings", "Configuration and transform names must be non-empty")
    if not configuration_path.startswith("ocio://"):
        config_file = Path(configuration_path).expanduser()
        if (
            not config_file.is_absolute()
            or not config_file.is_file()
            or config_file.suffix.lower()
            not in {
                ".ocio",
                ".ocioz",
            }
        ):
            return skill_error(
                "Invalid OCIO configuration",
                "configuration_path must be a built-in ocio:// URL or an existing absolute .ocio/.ocioz file",
            )
        configuration_path = str(config_file.resolve())

    required_types = (
        "OpenColorIOConfiguration",
        "OpenColorIOConfigurationFactoryNew",
        "OpenColorIOColorSpace",
        "OpenColorIODisplayView",
        "FilePath",
    )
    missing = [name for name in required_types if getattr(unreal, name, None) is None]
    if missing:
        return skill_error(
            "OpenColorIO unavailable",
            f"Enable the OpenColorIO plugin; missing Unreal types: {', '.join(missing)}",
        )

    destination_path, asset_name = asset_path.rsplit("/", 1)
    object_path = f"{asset_path}.{asset_name}"
    asset = unreal.EditorAssetLibrary.load_asset(object_path)
    created = asset is None
    if asset is not None and not isinstance(asset, unreal.OpenColorIOConfiguration):
        return skill_error(
            f"Existing asset is not an OpenColorIO Configuration: {object_path}",
            f"Loaded asset type: {type(asset).__name__}",
        )
    if asset is None:
        unreal.EditorAssetLibrary.make_directory(destination_path)
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            asset_name,
            destination_path,
            unreal.OpenColorIOConfiguration,
            unreal.OpenColorIOConfigurationFactoryNew(),
        )
        if asset is None:
            return skill_error(
                f"Failed to create OpenColorIO Configuration: {object_path}",
                "AssetTools.create_asset returned None",
            )

    source = unreal.OpenColorIOColorSpace(color_space_name=source_color_space, family_name="")
    display_view = unreal.OpenColorIODisplayView(display=display, view=view)
    asset.set_editor_property("configuration_file", unreal.FilePath(file_path=configuration_path))
    asset.set_editor_property("desired_color_spaces", [source])
    asset.set_editor_property("desired_display_views", [display_view])
    asset.reload_existing_colorspaces(True)

    loaded_sources = asset.get_editor_property("desired_color_spaces")
    loaded_views = asset.get_editor_property("desired_display_views")
    if not any(item.color_space_name == source_color_space for item in loaded_sources) or not any(
        item.display == display and item.view == view for item in loaded_views
    ):
        return skill_error(
            "Invalid OCIO transform",
            "The configuration did not retain the requested source color space and display-view",
        )
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
        return skill_error(
            f"Failed to save OpenColorIO Configuration: {object_path}",
            "EditorAssetLibrary.save_loaded_asset returned False",
        )

    if apply_to_active_viewport:
        viewport_types = (
            "OpenColorIOEditorBlueprintLibrary",
            "OpenColorIOColorConversionSettings",
            "OpenColorIODisplayConfiguration",
            "OpenColorIOViewTransformDirection",
        )
        missing = [name for name in viewport_types if getattr(unreal, name, None) is None]
        if missing:
            return skill_error(
                "Viewport OpenColorIO unavailable",
                f"Enable the OpenColorIO Editor plugin; missing Unreal types: {', '.join(missing)}",
            )
        conversion = unreal.OpenColorIOColorConversionSettings(
            configuration_source=asset,
            source_color_space=source,
            destination_display_view=display_view,
            display_view_direction=unreal.OpenColorIOViewTransformDirection.FORWARD,
        )
        unreal.OpenColorIOEditorBlueprintLibrary.set_active_viewport_configuration(
            unreal.OpenColorIODisplayConfiguration(
                is_enabled=True,
                color_configuration=conversion,
            )
        )

    return skill_success(
        f"Configured OpenColorIO asset '{asset_path}'",
        prompt="Select this asset under the Level Viewport OCIO Display settings.",
        asset_path=asset_path,
        object_path=object_path,
        configuration_path=configuration_path,
        source_color_space=source_color_space,
        display=display,
        view=view,
        created=created,
        transform_valid=True,
        active_viewport_configured=bool(apply_to_active_viewport),
    )


def main(**kwargs) -> dict:
    return create_ocio_configuration(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
