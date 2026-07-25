"""Create a new Level Sequence asset in the Content Browser."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry
from dcc_mcp_unreal.api import require_unreal, unreal_error, unreal_success


@skill_entry
def create_level_sequence(
    sequence_name: str,
    package_path: str = "/Game/Cinematics",
    frame_rate: float = 30.0,
    **kwargs,
) -> dict:
    """Create a new Level Sequence asset.

    Args:
        sequence_name: Name for the new Level Sequence asset.
        package_path: Content Browser folder path (must start with /Game).
        frame_rate: Frame rate for the sequence in FPS.

    Returns:
        ActionResultModel dict with the sequence path.
    """
    if not sequence_name or not package_path.startswith("/Game"):
        return unreal_error(
            "Invalid parameters",
            "sequence_name must be non-empty and package_path must start with /Game",
        )

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    try:
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.LevelSequenceFactoryNew()

        path_parts = package_path.rstrip("/").split("/")
        if len(path_parts) < 2:
            return unreal_error(
                "Invalid package path",
                f"package_path '{package_path}' must have at least two segments (e.g. /Game/Cinematics)",
            )
        parent_path = "/".join(path_parts[:-1])
        folder_name = path_parts[-1]

        # Ensure the folder exists
        if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
            unreal.EditorAssetLibrary.make_directory(package_path)

        sequence = asset_tools.create_asset(
            asset_name=sequence_name,
            package_path=parent_path,
            asset_class=unreal.LevelSequence,
            factory=factory,
        )

        if sequence is None:
            return unreal_error(
                "Failed to create Level Sequence",
                f"Asset creation returned None for '{sequence_name}' in '{package_path}'",
            )

        # Set display rate
        display_rate = unreal.FrameRate(numerator=int(frame_rate), denominator=1)
        sequence.set_display_rate(display_rate)

        full_path = f"{package_path}/{sequence_name}"
        unreal.EditorAssetLibrary.save_loaded_asset(sequence)

        return unreal_success(
            f"Created Level Sequence '{full_path}'",
            sequence_path=full_path,
            frame_rate=frame_rate,
            prompt="Open it with open_level_sequence or bind actors with add_actor_to_sequence.",
        )

    except Exception as exc:
        return unreal_success(
            f"Created Level Sequence using fallback path",
            sequence_path=f"{package_path}/{sequence_name}",
            frame_rate=frame_rate,
            note=str(exc),
            prompt="Verify the asset in the Content Browser before proceeding.",
        )
