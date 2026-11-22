import importlib.util
import sys
from types import SimpleNamespace


def _load():
    path = "src/dcc_mcp_unreal/skills/unreal-assets/scripts/apply_asset_handoff.py"
    spec = importlib.util.spec_from_file_location("apply_asset_handoff", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan():
    return {
        "schema": "dcc-mcp-unreal.asset-handoff-plan.v1",
        "status": "planned",
        "overwrite_allowed": False,
        "copy": [{"source": "/Plugin/Textures/T_Mud", "destination": "/Game/Localized/T_Mud"}],
    }


def test_apply_requires_a_live_unreal_host(monkeypatch):
    monkeypatch.setitem(sys.modules, "unreal", None)
    result = _load().apply_asset_handoff(plan=_plan())
    assert result["success"] is False
    assert result["context"]["error_kind"] == "host_unavailable"


def test_apply_copies_and_rewrites_referencers(monkeypatch):
    copied = []

    class AssetTools:
        def duplicate_asset(self, name, package, source):
            copied.append((name, package, source))
            return object()

    class AssetLibrary:
        @staticmethod
        def does_asset_exist(_path):
            return False

        @staticmethod
        def load_asset(path):
            return path

        @staticmethod
        def save_asset(_path, only_if_is_dirty=False):
            return True

        @staticmethod
        def consolidate_assets(destination, sources):
            return destination == "/Game/Localized/T_Mud" and sources == ["/Plugin/Textures/T_Mud"]

    host = SimpleNamespace(
        EditorAssetLibrary=AssetLibrary,
        AssetToolsHelpers=SimpleNamespace(get_asset_tools=lambda: AssetTools()),
    )
    monkeypatch.setitem(sys.modules, "unreal", host)
    result = _load().apply_asset_handoff(plan=_plan())
    assert result["success"] is True
    assert result["context"]["status"] == "applied_unverified"
    assert result["context"]["reference_rewrite"] == "performed"
    assert result["context"]["rewritten_references"] == [
        {"source": "/Plugin/Textures/T_Mud", "destination": "/Game/Localized/T_Mud"}
    ]
    assert copied == [("T_Mud", "/Game/Localized", "/Plugin/Textures/T_Mud")]


def test_apply_can_skip_reference_rewrites_explicitly(monkeypatch):
    copied = []

    class AssetTools:
        def duplicate_asset(self, name, package, source):
            copied.append((name, package, source))
            return object()

    class AssetLibrary:
        @staticmethod
        def does_asset_exist(_path):
            return False

        @staticmethod
        def load_asset(path):
            return path

        @staticmethod
        def save_asset(_path, only_if_is_dirty=False):
            return True

    host = SimpleNamespace(
        EditorAssetLibrary=AssetLibrary, AssetToolsHelpers=SimpleNamespace(get_asset_tools=lambda: AssetTools())
    )
    monkeypatch.setitem(sys.modules, "unreal", host)
    result = _load().apply_asset_handoff(plan=_plan(), rewrite_references=False)
    assert result["success"] is True
    assert result["context"]["reference_rewrite"] == "skipped_by_request"
