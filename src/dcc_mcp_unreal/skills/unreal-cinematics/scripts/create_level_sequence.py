"""Create a new Level Sequence asset in the Content Browser."""

from __future__ import annotations

import math
from fractions import Fraction

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_unreal.api import unreal_error, unreal_from_exception, unreal_success


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
    package_path = package_path.rstrip("/")
    if not sequence_name or not (package_path == "/Game" or package_path.startswith("/Game/")):
        return unreal_error(
            "Invalid parameters",
            "sequence_name must be non-empty and package_path must be /Game or start with /Game/",
        )
    if not math.isfinite(frame_rate) or frame_rate <= 0:
        return unreal_error("Invalid frame_rate", "frame_rate must be a finite number greater than zero")

    try:
        import unreal  # noqa: PLC0415
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")

    sequence = None
    full_path = f"{package_path}/{sequence_name}"
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(full_path):
            return unreal_error("Level Sequence already exists", f"An asset already exists at '{full_path}'.")

        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.LevelSequenceFactoryNew()

        # Ensure the folder exists
        if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
            unreal.EditorAssetLibrary.make_directory(package_path)
        if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
            return unreal_error("Failed to create package path", f"Could not create '{package_path}'.")

        sequence = asset_tools.create_asset(
            asset_name=sequence_name,
            package_path=package_path,
            asset_class=unreal.LevelSequence,
            factory=factory,
        )

        if sequence is None:
            return unreal_error(
                "Failed to create Level Sequence",
                f"Asset creation returned None for '{sequence_name}' in '{package_path}'",
            )

        # Set display rate
        rate = Fraction(str(frame_rate)).limit_denominator(1001)
        display_rate = unreal.FrameRate(numerator=rate.numerator, denominator=rate.denominator)
        sequence.set_display_rate(display_rate)

        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence):
            unreal.EditorAssetLibrary.delete_asset(full_path)
            return unreal_error("Failed to save Level Sequence", f"Unreal could not save '{full_path}'.")

        saved_sequence = unreal.load_asset(full_path)
        if saved_sequence is None:
            unreal.EditorAssetLibrary.delete_asset(full_path)
            return unreal_error("Level Sequence verification failed", f"Saved asset '{full_path}' could not be loaded.")

        return unreal_success(
            f"Created Level Sequence '{full_path}'",
            sequence_path=full_path,
            frame_rate=rate.numerator / rate.denominator,
            frame_rate_numerator=rate.numerator,
            frame_rate_denominator=rate.denominator,
            prompt="Open it with open_level_sequence or bind actors with add_actor_to_sequence.",
        )

    except Exception as exc:
        if sequence is not None:
            try:
                unreal.EditorAssetLibrary.delete_asset(full_path)
            except Exception:
                pass
        return unreal_from_exception(
            exc,
            f"Failed to create Level Sequence '{full_path}'",
            sequence_path=full_path,
        )
