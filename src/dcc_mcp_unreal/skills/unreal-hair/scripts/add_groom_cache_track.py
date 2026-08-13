"""Add a Groom Cache section to an existing Level Sequence."""

from __future__ import annotations

from _hair_runtime import load_typed, versioned_binding_name
from dcc_mcp_core.skill import skill_entry, skill_error, skill_exception, skill_success


@skill_entry
def add_groom_cache_track(
    sequence_path: str = "",
    component_path: str = "",
    groom_cache_path: str = "",
    start_frame: int = 0,
    end_frame: int = 150,
    play_rate: float = 1.0,
    reverse: bool = False,
    binding_name: str = "VellumGroomCache",
    **kwargs,
) -> dict:
    """Create one new possessable/track; never replace an existing Cache asset."""
    import unreal  # noqa: PLC0415

    if start_frame < 0 or end_frame <= start_frame or play_rate <= 0:
        return skill_error(
            "Invalid Groom Cache section range",
            "start_frame must be >= 0, end_frame > start_frame, and play_rate > 0",
        )
    try:
        sequence = load_typed(unreal, sequence_path, unreal.LevelSequence, "sequence_path")
        component = load_typed(unreal, component_path, unreal.GroomComponent, "component_path")
        cache = load_typed(unreal, groom_cache_path, unreal.GroomCache, "groom_cache_path")
        requested_binding_name = binding_name or "VellumGroomCache"
        versioned_name = versioned_binding_name(sequence, requested_binding_name)
        binding = sequence.add_possessable(component)
        binding.set_display_name(versioned_name)
        track = binding.add_track(unreal.MovieSceneGroomCacheTrack)
        section = track.add_section()
        section.set_range(start_frame, end_frame)
        params = section.get_editor_property("params")
        params.set_editor_property("groom_cache", cache)
        params.set_editor_property("play_rate", float(play_rate))
        params.set_editor_property("reverse", bool(reverse))
        section.set_editor_property("params", params)
        unreal.EditorAssetLibrary.save_loaded_asset(sequence, only_if_is_dirty=False)
        return skill_success(
            "Added Groom Cache track to the Level Sequence",
            sequence_path=sequence.get_path_name(),
            component_path=component.get_path_name(),
            groom_cache_path=cache.get_path_name(),
            requested_binding_name=requested_binding_name,
            binding_name=versioned_name,
            start_frame=start_frame,
            end_frame=end_frame,
            play_rate=float(play_rate),
            reverse=bool(reverse),
        )
    except ValueError as exc:
        return skill_error("Invalid Groom Cache track target", str(exc))
    except Exception as exc:
        return skill_exception(exc, message="Failed to add Groom Cache track")
