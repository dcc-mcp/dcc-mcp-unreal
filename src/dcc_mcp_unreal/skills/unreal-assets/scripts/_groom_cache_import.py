"""Compatibility and safety helpers for Unreal Groom Cache imports."""

from __future__ import annotations


def groom_cache_candidate_paths(destination_path: str, asset_name: str) -> tuple[str, str]:
    """Return the requested package path and HairStrandsFactory cache path."""
    package_path = "{}/{}".format(destination_path.rstrip("/"), asset_name)
    return package_path, "{}_strands_cache".format(package_path)


def versioned_groom_cache_name(editor_asset_library, destination_path: str, requested_name: str) -> str:
    """Choose a free, append-only name without replacing a Groom Cache."""
    for version in range(1000):
        candidate = requested_name if version == 0 else "{}_v{:03d}".format(requested_name, version)
        paths = groom_cache_candidate_paths(destination_path, candidate)
        if not any(editor_asset_library.does_asset_exist(path) for path in paths):
            return candidate
    raise RuntimeError("No free Groom Cache version found after 1000 candidates")


def object_path(value) -> str:
    """Return an Unreal object path from an asset or package path."""
    path = str(value).split(".", 1)[0]
    leaf = path.rsplit("/", 1)[-1]
    return "{}.{}".format(path, leaf)
