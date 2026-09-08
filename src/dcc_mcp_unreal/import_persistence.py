"""Persist only assets produced by a synchronous import in its destination."""

from __future__ import annotations


def _within(path, destination):
    return str(path).split(".", 1)[0].startswith(destination + "/")


def import_snapshot(unreal, destination):
    """Refuse to include pre-existing unsaved work in an automated import."""
    dirty = [
        str(package.get_name())
        for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
        if _within(package.get_name(), destination)
    ]
    if dirty:
        raise ValueError("Destination contains unsaved assets: " + ", ".join(sorted(dirty)))
    return set(unreal.EditorAssetLibrary.list_assets(destination, recursive=True, include_folder=False))


def persist_import(unreal, destination, before, imported_paths):
    """Save new assets and importer-dirtied dependencies without a directory save."""
    after = set(unreal.EditorAssetLibrary.list_assets(destination, recursive=True, include_folder=False))
    dirty = {
        str(package.get_name())
        for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
        if _within(package.get_name(), destination)
    }
    candidates = set(imported_paths) | (after - before)
    candidates.update(path for path in after if str(path).split(".", 1)[0] in dirty)
    saved, failed = [], []
    for path in sorted(candidates):
        if not _within(path, destination):
            failed.append({"path": path, "reason": "outside_destination"})
            continue
        try:
            asset = unreal.EditorAssetLibrary.load_asset(path)
            if asset is None:
                failed.append({"path": path, "reason": "load_failed"})
            elif not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
                failed.append({"path": path, "reason": "save_failed"})
            else:
                saved.append(path)
        except Exception as exc:  # A partial import must not be reported as durable success.
            failed.append({"path": path, "reason": str(exc)})
    return {"status": "saved" if not failed else "incomplete", "saved_asset_paths": saved, "failures": failed}
