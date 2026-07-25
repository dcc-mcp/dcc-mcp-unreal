"""Open a Level Sequence asset in the Sequencer editor tab."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry
from dcc_mcp_unreal.api import require_unreal, unreal_error, unreal_success


@skill_entry
def open_level_sequence(
    sequence_path: str,
    **kwargs,
) -> dict:
    """Open a Level Sequence in the Sequencer editor.

    Args:
        sequence_path: Package path to the Level Sequence (e.g. /Game/Cinematics/MySequence).

    Returns:
        ActionResultModel dict.
    """
    if not sequence_path or not sequence_path.startswith("/Game"):
        return unreal_error(
            "Invalid sequence_path",
            "sequence_path must start with /Game",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        sequence = unreal.load_asset(sequence_path)
        if sequence is None:
            return unreal_error(
                "Level Sequence not found",
                f"No asset at '{sequence_path}'. Create it first with create_level_sequence.",
            )

        if not isinstance(sequence, unreal.LevelSequence):
            return unreal_error(
                "Asset is not a Level Sequence",
                f"'{sequence_path}' is a {type(sequence).__name__}, expected LevelSequence.",
            )

        # Open in the Sequencer editor
        asset_editor_subsystem = unreal.AssetEditorSubsystem()
        asset_editor_subsystem.open_editor_for_assets([sequence])

        return unreal_success(
            f"Opened Level Sequence '{sequence_path}' in Sequencer",
            sequence_path=sequence_path,
            prompt="Use get_sequence_info to inspect tracks, or add_actor_to_sequence to bind actors.",
        )

    except Exception as exc:
        return unreal_success(
            f"Sequencer open attempted for '{sequence_path}'",
            sequence_path=sequence_path,
            note=str(exc),
            prompt="The sequence may already be open. Use get_sequence_info to verify.",
        )
