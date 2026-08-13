"""Exact-path helpers for Unreal Groom runtime operations."""

from __future__ import annotations


def load_typed(unreal, object_path: str, expected_type, label: str):
    """Load one exact Unreal object path and enforce its reflected class."""
    value = unreal.load_object(None, object_path) if object_path else None
    if value is None or not isinstance(value, expected_type):
        raise ValueError("{} must resolve to {}: {}".format(label, expected_type.__name__, object_path))
    return value


def optional_path(value) -> str | None:
    return value.get_path_name() if value is not None else None


def groom_topology(groom) -> dict:
    if groom is None:
        return {
            "groom_group_count": 0,
            "groom_curve_count": 0,
            "groom_guide_count": 0,
            "groom_curve_vertex_count": 0,
            "groom_guide_vertex_count": 0,
        }
    groups = list(groom.get_editor_property("hair_groups_info"))
    return {
        "groom_group_count": len(groups),
        "groom_curve_count": sum(int(group.get_editor_property("num_curves")) for group in groups),
        "groom_guide_count": sum(int(group.get_editor_property("num_guides")) for group in groups),
        "groom_curve_vertex_count": sum(int(group.get_editor_property("num_curve_vertices")) for group in groups),
        "groom_guide_vertex_count": sum(int(group.get_editor_property("num_guide_vertices")) for group in groups),
    }


def component_state(component) -> dict:
    groom = component.get_editor_property("groom_asset")
    return {
        "component_path": component.get_path_name(),
        "groom_asset_path": optional_path(groom),
        "groom_cache_path": optional_path(component.get_editor_property("groom_cache")),
        "running": bool(component.get_editor_property("running")),
        "looping": bool(component.get_editor_property("looping")),
        "manual_tick": bool(component.get_editor_property("manual_tick")),
        **groom_topology(groom),
    }


def versioned_binding_name(sequence, requested_name: str) -> str:
    existing = {str(binding.get_display_name()) for binding in sequence.get_bindings()}
    for version in range(1000):
        candidate = requested_name if version == 0 else "{}_v{:03d}".format(requested_name, version)
        if candidate not in existing:
            return candidate
    raise RuntimeError("No free Groom Cache binding name found after 1000 candidates")
