"""Shared PIE-session and runtime actor-resolution contracts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest


class _Actor:
    def __init__(self, name: str, label: Optional[str] = None):
        self._name = name
        self._label = label or name

    def get_name(self):
        return self._name

    def get_actor_label(self):
        return self._label


def _fake_unreal(*, game_world=None, runtime_actors=(), editor_actors=(), reports_pie=False):
    class Actor:
        pass

    class LevelEditorSubsystem:
        def is_in_play_in_editor(self):
            return reports_pie

    class UnrealEditorSubsystem:
        def get_game_world(self):
            return game_world

    class EditorActorSubsystem:
        def get_all_level_actors(self):
            return list(editor_actors)

    class GameplayStatics:
        @staticmethod
        def get_all_actors_of_class(world, actor_class):
            assert world is game_world
            assert actor_class is Actor
            return list(runtime_actors)

        @staticmethod
        def get_player_controller(_world, _index):
            return object()

        @staticmethod
        def get_player_pawn(_world, _index):
            return object()

    def get_editor_subsystem(subsystem_class):
        return subsystem_class()

    return SimpleNamespace(
        log=lambda _message: None,
        Actor=Actor,
        LevelEditorSubsystem=LevelEditorSubsystem,
        UnrealEditorSubsystem=UnrealEditorSubsystem,
        EditorActorSubsystem=EditorActorSubsystem,
        GameplayStatics=GameplayStatics,
        EditorLevelLibrary=SimpleNamespace(get_all_level_actors=lambda: list(editor_actors)),
        get_editor_subsystem=get_editor_subsystem,
    )


def test_find_level_actor_prefers_actor_from_active_pie_world(monkeypatch):
    from dcc_mcp_unreal.api import find_level_actor

    runtime_actor = _Actor("CBP_MPS_Neil_C_0")
    unreal = _fake_unreal(
        game_world=object(),
        runtime_actors=[runtime_actor],
        editor_actors=[_Actor("EditorOnlyActor")],
        reports_pie=False,
    )
    monkeypatch.setitem(sys.modules, "unreal", unreal)

    assert find_level_actor("CBP_MPS_Neil_C_0") is runtime_actor


def test_game_world_is_the_shared_source_of_truth_for_pie_activity(monkeypatch):
    from dcc_mcp_unreal.pie_session import require_pie_context

    world = object()
    unreal = _fake_unreal(game_world=world, reports_pie=False)
    monkeypatch.setitem(sys.modules, "unreal", unreal)

    context = require_pie_context()

    assert context.world is world


def test_missing_pie_world_has_stable_retryable_error_contract(monkeypatch):
    from dcc_mcp_unreal.pie_session import PieSessionUnavailableError, require_pie_context

    monkeypatch.setitem(sys.modules, "unreal", _fake_unreal())

    with pytest.raises(PieSessionUnavailableError) as captured:
        require_pie_context()

    assert captured.value.code == "pie_session_unavailable"
    assert captured.value.retryable is True


def test_pie_session_error_result_is_machine_classified_as_retryable():
    from dcc_mcp_unreal.pie_session import PieSessionUnavailableError, pie_session_error

    result = pie_session_error(PieSessionUnavailableError("PIE world is transitioning"))

    assert result["success"] is False
    assert result["error"] == "pie_session_unavailable"
    assert result["context"]["retryable"] is True
    assert result["context"]["reason"] == "PIE world is transitioning"


def test_list_actors_uses_same_active_pie_actor_set(monkeypatch):
    runtime_actor = _Actor("CBP_MPS_Neil_C_0")
    unreal = _fake_unreal(
        game_world=object(),
        runtime_actors=[runtime_actor],
        editor_actors=[_Actor("EditorOnlyActor")],
    )
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    script = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "dcc_mcp_unreal"
        / "skills"
        / "unreal-actors"
        / "scripts"
        / "list_actors.py"
    )
    spec = importlib.util.spec_from_file_location("_test_list_pie_actors", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    result = module.list_actors()

    assert result["context"]["actors"] == ["CBP_MPS_Neil_C_0"]
