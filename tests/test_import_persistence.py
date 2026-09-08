"""Save importer-created dependencies while protecting existing unsaved work."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dcc_mcp_unreal.import_persistence import import_snapshot, persist_import


def host(before=(), after=(), dirty_before=(), dirty_after=()):
    def packages(names):
        return [SimpleNamespace(get_name=lambda name=name: name) for name in names]

    library = SimpleNamespace(
        list_assets=Mock(side_effect=[list(before), list(after)]),
        load_asset=Mock(side_effect=lambda path: path),
        save_loaded_asset=Mock(return_value=True),
    )
    return SimpleNamespace(
        EditorAssetLibrary=library,
        EditorLoadingAndSavingUtils=SimpleNamespace(
            get_dirty_content_packages=Mock(side_effect=[packages(dirty_before), packages(dirty_after)])
        ),
    )


def test_import_saves_dependencies_omitted_from_task_results():
    tree, material, texture, existing = (f"/Game/Verify/{name}.{name}" for name in ("Tree", "Mat", "Tex", "Other"))
    unreal = host([existing], [tree, material, texture, existing])
    before = import_snapshot(unreal, "/Game/Verify")
    result = persist_import(unreal, "/Game/Verify", before, [tree])
    assert result["status"] == "saved"
    assert set(result["saved_asset_paths"]) == {tree, material, texture}
    assert existing not in result["saved_asset_paths"]


def test_preexisting_dirty_destination_is_rejected_before_import():
    unreal = host(dirty_before=["/Game/Verify/UserWork"])
    with pytest.raises(ValueError, match="unsaved assets"):
        import_snapshot(unreal, "/Game/Verify")
    unreal.EditorAssetLibrary.save_loaded_asset.assert_not_called()


def test_importer_dirtied_existing_dependency_is_saved_but_external_work_is_ignored():
    path = "/Game/Verify/Material.Material"
    unreal = host([path], [path], ["/Game/VerifyOther/Dirty"], ["/Game/Verify/Material", "/Game/VerifyOther/Dirty"])
    result = persist_import(unreal, "/Game/Verify", import_snapshot(unreal, "/Game/Verify"), [])
    assert result["saved_asset_paths"] == [path]


def test_partial_save_and_outside_destination_are_not_reported_as_success():
    paths = ["/Game/Verify/Mesh.Mesh", "/Game/Verify/Mat.Mat"]
    unreal = host(after=paths)
    unreal.EditorAssetLibrary.save_loaded_asset.side_effect = lambda path, **kw: "Mat.Mat" not in path
    result = persist_import(unreal, "/Game/Verify", import_snapshot(unreal, "/Game/Verify"), [*paths, "/Game/Other.X"])
    assert result["status"] == "incomplete"
    assert result["saved_asset_paths"] == [paths[0]]
    assert {row["reason"] for row in result["failures"]} == {"save_failed", "outside_destination"}


def test_unloadable_import_output_is_a_persistence_failure():
    unreal = host()
    unreal.EditorAssetLibrary.load_asset.return_value = None
    unreal.EditorAssetLibrary.load_asset.side_effect = None
    result = persist_import(
        unreal, "/Game/Verify", import_snapshot(unreal, "/Game/Verify"), ["/Game/Verify/Missing.Missing"]
    )
    assert result["failures"] == [{"path": "/Game/Verify/Missing.Missing", "reason": "load_failed"}]
