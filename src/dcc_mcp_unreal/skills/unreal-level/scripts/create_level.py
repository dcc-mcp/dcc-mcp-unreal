"""Create and save a new Unreal Engine level."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def create_level(level_path: str, **_kwargs) -> dict:
    if not level_path.startswith("/Game/") or level_path.endswith("/"):
        return skill_error("Invalid level_path", "level_path must be a /Game/... asset path")

    import unreal  # noqa: PLC0415

    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        return skill_error("Level already exists", f"An asset already exists at '{level_path}'")
    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if subsystem is None or not subsystem.new_level(level_path):
        return skill_error("Failed to create level", f"LevelEditorSubsystem rejected '{level_path}'")
    if not unreal.EditorLevelLibrary.save_current_level():
        return skill_error("Failed to save level", f"Could not save '{level_path}'")
    if not unreal.EditorAssetLibrary.does_asset_exist(level_path):
        return skill_error("Level verification failed", f"Saved level '{level_path}' is not in the asset registry")

    return skill_success(
        f"Created level '{level_path}'",
        level_path=level_path,
        prompt="Use unreal_actors__spawn_actor to populate the new level.",
    )


def main(**kwargs) -> dict:
    return create_level(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
