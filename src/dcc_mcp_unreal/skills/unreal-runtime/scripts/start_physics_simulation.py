"""Start Unreal's Simulation-in-Editor physics mode."""

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def start_physics_simulation(**kwargs) -> dict:
    """Start in-editor simulation so Chaos assets execute their real physics."""
    import unreal  # noqa: PLC0415

    try:
        unreal.EditorLevelLibrary.editor_play_simulate()
    except Exception as exc:
        return skill_error("Failed to start physics simulation", str(exc))
    return skill_success(
        "Started Unreal in-editor physics simulation",
        prompt="Capture the viewport, then stop it with unreal_runtime__stop_physics_simulation.",
    )
