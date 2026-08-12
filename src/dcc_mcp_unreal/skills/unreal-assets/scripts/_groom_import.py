"""Compatibility and safety helpers for static Unreal Groom imports."""

from __future__ import annotations


def versioned_groom_name(editor_asset_library, destination_path: str, requested_name: str) -> str:
    """Choose a free append-only Groom package name."""
    folder = destination_path.rstrip("/")
    for version in range(1000):
        candidate = requested_name if version == 0 else "{}_v{:03d}".format(requested_name, version)
        if not editor_asset_library.does_asset_exist("{}/{}".format(folder, candidate)):
            return candidate
    raise RuntimeError("No free static Groom version found after 1000 candidates")


def groom_topology(asset) -> dict:
    """Return JSON-safe aggregate topology from reflected Groom groups."""
    groups = list(asset.get_editor_property("hair_groups_info"))
    return {
        "group_count": len(groups),
        "curve_count": sum(int(group.get_editor_property("num_curves")) for group in groups),
        "guide_count": sum(int(group.get_editor_property("num_guides")) for group in groups),
        "curve_vertex_count": sum(int(group.get_editor_property("num_curve_vertices")) for group in groups),
        "guide_vertex_count": sum(int(group.get_editor_property("num_guide_vertices")) for group in groups),
    }


def vector3(value, field: str) -> tuple[float, float, float]:
    """Validate and normalize one JSON three-vector."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("{} must contain three numeric values".format(field))
    try:
        return tuple(float(component) for component in value)
    except (TypeError, ValueError) as exc:
        raise ValueError("{} must contain three numeric values".format(field)) from exc
