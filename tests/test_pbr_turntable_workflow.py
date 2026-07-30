from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_create_level_saves_and_verifies_asset(monkeypatch):
    unreal = ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.LevelEditorSubsystem = type("LevelEditorSubsystem", (), {})
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.does_asset_exist.side_effect = [False, True]
    unreal.EditorLevelLibrary = MagicMock()
    unreal.EditorLevelLibrary.save_current_level.return_value = True
    subsystem = MagicMock()
    subsystem.new_level.return_value = True
    unreal.get_editor_subsystem = MagicMock(return_value=subsystem)
    monkeypatch.setitem(sys.modules, "unreal", unreal)

    result = _load(
        "create_level",
        "src/dcc_mcp_unreal/skills/unreal-level/scripts/create_level.py",
    ).create_level(level_path="/Game/Drawcall557/Maps/L_Lookdev")

    assert result["success"] is True
    subsystem.new_level.assert_called_once_with("/Game/Drawcall557/Maps/L_Lookdev")


def test_spawn_actor_assigns_static_mesh_and_reports_bounds(monkeypatch):
    unreal = ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.StaticMesh = type("StaticMesh", (), {})
    unreal.StaticMeshComponent = type("StaticMeshComponent", (), {})
    mesh = unreal.StaticMesh()
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.load_asset.return_value = mesh
    unreal.Vector = lambda x, y, z: (x, y, z)
    unreal.Rotator = lambda x, y, z: (x, y, z)
    unreal.load_class = MagicMock(return_value=object())
    component = MagicMock()
    actor = MagicMock()
    actor.get_name.return_value = "StaticMeshActor_1"
    actor.get_component_by_class.return_value = component
    actor.get_actor_bounds.return_value = (
        SimpleNamespace(x=1.0, y=2.0, z=3.0),
        SimpleNamespace(x=4.0, y=5.0, z=6.0),
    )
    unreal.EditorLevelLibrary = MagicMock()
    unreal.EditorLevelLibrary.spawn_actor_from_class.return_value = actor
    monkeypatch.setitem(sys.modules, "unreal", unreal)

    result = _load(
        "spawn_static_mesh_actor",
        "src/dcc_mcp_unreal/skills/unreal-actors/scripts/spawn_actor.py",
    ).spawn_actor(static_mesh_path="/Game/Meshes/SM_Gun")

    assert result["success"] is True
    component.set_static_mesh.assert_called_once_with(mesh)
    assert result["context"]["bounds"]["extent"] == [4.0, 5.0, 6.0]


def test_set_actor_transform_accepts_spawned_actor_label(monkeypatch):
    unreal = ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.Vector = lambda x, y, z: SimpleNamespace(x=x, y=y, z=z)
    unreal.Rotator = lambda **rotation: SimpleNamespace(**rotation)
    unreal.Transform = lambda location, rotation, scale: (location, rotation, scale)
    actor = MagicMock()
    actor.get_actor_location.return_value = SimpleNamespace(x=0.0, y=0.0, z=0.0)
    actor.get_actor_rotation.return_value = SimpleNamespace(pitch=0.0, yaw=0.0, roll=0.0)
    actor.get_actor_scale3d.return_value = SimpleNamespace(x=1.0, y=1.0, z=1.0)
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    import dcc_mcp_unreal.api

    monkeypatch.setattr(dcc_mcp_unreal.api, "find_level_actor", MagicMock(return_value=actor))

    result = _load(
        "set_actor_transform_by_label",
        "src/dcc_mcp_unreal/skills/unreal-actors/scripts/set_actor_transform.py",
    ).set_actor_transform(actor_name="Lookdev_Floor", rotation_pitch=-8.4, rotation_yaw=90.0, scale_x=4.0)

    assert result["success"] is True
    assert result["context"]["rotation"] == [-8.4, 90.0, 0.0]
    actor.set_actor_transform.assert_called_once()


def test_start_render_requires_a_queued_job(monkeypatch):
    unreal = ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.MoviePipelineQueueSubsystem = type("MoviePipelineQueueSubsystem", (), {})
    subsystem = MagicMock()
    subsystem.is_rendering.return_value = False
    subsystem.get_queue.return_value.get_jobs.return_value = []
    unreal.get_editor_subsystem = MagicMock(return_value=subsystem)
    monkeypatch.setitem(sys.modules, "unreal", unreal)

    result = _load(
        "start_queued_render",
        "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/start_queued_render.py",
    ).start_queued_render()

    assert result["success"] is False
    assert result["message"] == "Movie Render Queue is empty"
