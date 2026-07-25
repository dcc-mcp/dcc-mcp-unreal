"""Stop Unreal's active Simulation-in-Editor physics mode."""

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def stop_physics_simulation(**kwargs) -> dict:
    """Stop the current physics simulation session."""
    import unreal  # noqa: PLC0415

    try:
        unreal.EditorLevelLibrary.editor_end_play()
    except Exception as exc:
        return skill_error("Failed to stop physics simulation", str(exc))
    return skill_success("Stopped Unreal in-editor physics simulation")
