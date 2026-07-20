"""Save the current Unreal Engine level."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def save_level(
    save_all_dirty: bool = False,
    **kwargs,
) -> dict:
    """Save the current persistent level.

    Args:
        save_all_dirty: If ``True``, also save all other dirty (unsaved)
            packages in the project, not just the current level.

    Returns:
        dict: ActionResultModel confirming the save.
    """
    import unreal  # noqa: PLC0415

    world = unreal.EditorLevelLibrary.get_editor_world()
    if world is None:
        return skill_error(
            "No editor world available",
            "EditorLevelLibrary.get_editor_world() returned None",
            prompt="Ensure Unreal Editor is fully loaded with an open level.",
        )

    level_name = world.get_name()

    # Save current level
    saved = unreal.EditorLevelLibrary.save_current_level()
    if not saved:
        return skill_error(
            f"Failed to save level '{level_name}'",
            "EditorLevelLibrary.save_current_level returned False",
            prompt="Check the Output Log for save errors.",
            possible_solutions=[
                "Ensure the level asset is not read-only",
                "Check that the project directory has write permissions",
                "Try File → Save from the Unreal Editor menu",
            ],
        )

    saved_packages: list = [level_name]

    # Optionally save all dirty packages
    if save_all_dirty:
        try:
            dirty_packages = unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
            if dirty_packages:
                unreal.EditorLoadingAndSavingUtils.save_packages(dirty_packages, only_if_is_dirty=True)
                saved_packages.extend([str(p.get_name()) for p in dirty_packages])
        except Exception as exc:
            # Non-fatal — level was saved, only dirty packages failed
            from dcc_mcp_core.skill import skill_warning

            return skill_warning(
                f"Level '{level_name}' saved; some dirty packages could not be saved",
                warning=str(exc),
                level_name=level_name,
                saved_packages=saved_packages,
            )

    return skill_success(
        f"Saved level '{level_name}'",
        prompt="Use load_level to open a different level, or get_level_info to inspect the current one.",
        level_name=level_name,
        saved_packages=saved_packages,
        saved_dirty_packages=save_all_dirty,
    )
