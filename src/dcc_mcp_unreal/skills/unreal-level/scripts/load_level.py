"""Load a level by asset path in Unreal Engine Editor."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry
from dcc_mcp_core.skill import skill_error
from dcc_mcp_core.skill import skill_success


@skill_entry
def load_level(
    level_path: str = "",
    save_current: bool = True,
    **kwargs,
) -> dict:
    """Load a level by its Content Browser asset path.

    Optionally saves the current level before loading the new one.
    The level path should point to a ``.umap`` asset in the Content Browser.

    Args:
        level_path: Content Browser path to the level asset
            (e.g. ``"/Game/Maps/MainMenu"`` or
            ``"/Game/Levels/TestLevel"``).
        save_current: If ``True`` (default), save the current level before
            loading the new one to avoid losing unsaved changes.

    Returns:
        dict: ActionResultModel with the loaded level name.
    """
    import unreal  # noqa: PLC0415

    if not level_path:
        return skill_error(
            "Missing required parameter: 'level_path'",
            "level_path must be a Content Browser path to a .umap asset",
            possible_solutions=[
                "Example: '/Game/Maps/MainMenu'",
                "Use list_assets with asset_class_filter='World' to find level assets",
            ],
        )

    # Save current level first if requested
    if save_current:
        current_world = unreal.EditorLevelLibrary.get_editor_world()
        if current_world is not None:
            saved = unreal.EditorLevelLibrary.save_current_level()
            if not saved:
                # Non-fatal — proceed with load anyway (user may have no changes)
                pass

    success = unreal.EditorLevelLibrary.load_level(level_path)
    if not success:
        return skill_error(
            f"Failed to load level: {level_path}",
            "EditorLevelLibrary.load_level returned False",
            prompt="Verify the level path exists in the Content Browser.",
            possible_solutions=[
                "Use list_assets with asset_class_filter='World' to find valid level paths",
                "Ensure the level asset is not already open in another editor window",
                "Check for unsaved changes that may be blocking the level switch",
            ],
        )

    # Get new level name
    new_world = unreal.EditorLevelLibrary.get_editor_world()
    new_level_name = new_world.get_name() if new_world else level_path.rsplit("/", 1)[-1]

    return skill_success(
        f"Loaded level '{new_level_name}'",
        prompt="Use get_level_info to inspect the loaded level.",
        level_path=level_path,
        level_name=new_level_name,
        previous_level_saved=save_current,
    )


def main(**kwargs) -> dict:
    return load_level(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main
    run_main(main)
