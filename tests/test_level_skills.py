"""Tests for Unreal level skill scripts."""

from __future__ import annotations

import importlib.util
import sys
import weakref
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _load_level_script():
    script = "src/dcc_mcp_unreal/skills/unreal-level/scripts/load_level.py"
    spec = importlib.util.spec_from_file_location("_test_load_level", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_load_releases_old_world_before_engine_switch(monkeypatch):
    class World:
        def get_name(self):
            return "NewLevel"

    old_world_owner = [World()]
    old_world = weakref.ref(old_world_owner[0])
    events = []
    switched = False

    def get_world():
        events.append("read-new" if switched else "read-old")
        return World() if switched else old_world_owner[0]

    def save():
        events.append("save")
        return True

    def load(path):
        nonlocal switched
        events.append("load")
        old_world_owner.clear()
        assert old_world() is None, "load_level retained the old World across the map switch"
        switched = True
        return True

    monkeypatch.setitem(
        sys.modules,
        "unreal",
        SimpleNamespace(
            EditorLevelLibrary=SimpleNamespace(get_editor_world=get_world, save_current_level=save, load_level=load)
        ),
    )
    result = _load_level_script().load_level(level_path="/Game/Maps/NewLevel")
    assert result["success"], result
    assert result["context"]["previous_level_saved"]
    assert events == ["save", "load", "read-new"]


@pytest.mark.parametrize("save_result", [False, None])
def test_default_load_refuses_failed_save(monkeypatch, save_result):
    load = MagicMock(return_value=True)
    read_world = MagicMock(return_value=SimpleNamespace(get_name=lambda: "OldLevel"))
    monkeypatch.setitem(
        sys.modules,
        "unreal",
        SimpleNamespace(
            EditorLevelLibrary=SimpleNamespace(
                get_editor_world=read_world,
                save_current_level=lambda: save_result,
                load_level=load,
            )
        ),
    )
    result = _load_level_script().load_level(level_path="/Game/Maps/NewLevel")
    assert not result["success"]
    assert "save_current_level" in str(result)
    load.assert_not_called()
    read_world.assert_not_called()


def test_save_level_uses_ue58_save_packages_signature():
    package = SimpleNamespace(get_name=lambda: "/Game/Materials/M_Road")
    loading_and_saving = SimpleNamespace(
        get_dirty_content_packages=lambda: [package],
        save_packages=MagicMock(),
    )
    unreal = SimpleNamespace(
        EditorLevelLibrary=SimpleNamespace(
            get_editor_world=lambda: SimpleNamespace(get_name=lambda: "PCG_City_Showcase"),
            save_current_level=lambda: True,
        ),
        EditorLoadingAndSavingUtils=loading_and_saving,
    )
    script = "src/dcc_mcp_unreal/skills/unreal-level/scripts/save_level.py"
    spec = importlib.util.spec_from_file_location("_test_save_level", script)
    module = importlib.util.module_from_spec(spec)

    with patch.dict(sys.modules, {"unreal": unreal}):
        spec.loader.exec_module(module)
        result = module.save_level(save_all_dirty=True)

    assert result["success"] is True
    loading_and_saving.save_packages.assert_called_once_with([package], True)


def test_save_level_reports_mrq_active_before_attempting_a_save():
    save_current_level = MagicMock(side_effect=AssertionError("save must not start"))
    mrq_subsystem = SimpleNamespace(is_rendering=lambda: True)
    unreal = SimpleNamespace(
        EditorLevelLibrary=SimpleNamespace(
            get_editor_world=lambda: None,
            save_current_level=save_current_level,
        ),
        MoviePipelineQueueSubsystem=type("MoviePipelineQueueSubsystem", (), {}),
        LevelEditorSubsystem=type("LevelEditorSubsystem", (), {}),
        get_editor_subsystem=lambda cls: mrq_subsystem if cls.__name__ == "MoviePipelineQueueSubsystem" else None,
    )
    script = "src/dcc_mcp_unreal/skills/unreal-level/scripts/save_level.py"
    spec = importlib.util.spec_from_file_location("_test_save_level_mrq", script)
    module = importlib.util.module_from_spec(spec)

    with patch.dict(sys.modules, {"unreal": unreal}):
        spec.loader.exec_module(module)
        result = module.save_level(save_all_dirty=True)

    assert result["success"] is False
    assert result["context"]["reason"] == "pie_or_mrq_active"
    assert result["context"]["pie_active"] is False
    assert result["context"]["mrq_active"] is True
    assert result["context"]["next_action"] == {
        "action": "poll_then_retry",
        "poll_tool": "unreal_cinematics__get_render_status",
        "poll_until": {"is_rendering": False},
        "retry_tool": "unreal_level__save_level",
        "retry_arguments": {"save_all_dirty": True},
    }
    save_current_level.assert_not_called()


def test_save_level_distinguishes_editor_not_loaded():
    save_current_level = MagicMock(side_effect=AssertionError("save must not start"))
    unreal = SimpleNamespace(
        EditorLevelLibrary=SimpleNamespace(
            get_editor_world=lambda: None,
            save_current_level=save_current_level,
        ),
    )
    script = "src/dcc_mcp_unreal/skills/unreal-level/scripts/save_level.py"
    spec = importlib.util.spec_from_file_location("_test_save_level_not_loaded", script)
    module = importlib.util.module_from_spec(spec)

    with patch.dict(sys.modules, {"unreal": unreal}):
        spec.loader.exec_module(module)
        result = module.save_level(save_all_dirty=False)

    assert result["success"] is False
    assert result["context"]["reason"] == "editor_not_loaded"
    assert result["context"]["pie_active"] is False
    assert result["context"]["mrq_active"] is False
    assert result["context"]["next_action"] == {
        "action": "retry_when_editor_loaded",
        "retry_tool": "unreal_level__save_level",
        "retry_arguments": {"save_all_dirty": False},
    }
    save_current_level.assert_not_called()
