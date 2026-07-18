"""Small compatibility helpers for Unreal AssetData API changes."""

from __future__ import annotations


def object_path(asset_data) -> str:
    """Return an object path on both legacy Unreal and UE 5.8+."""
    get_soft_path = getattr(asset_data, "get_soft_object_path", None)
    if callable(get_soft_path):
        return str(get_soft_path())

    legacy_path = getattr(asset_data, "object_path", None)
    if legacy_path:
        return str(legacy_path)

    return "{}.{}".format(asset_data.package_name, asset_data.asset_name)
