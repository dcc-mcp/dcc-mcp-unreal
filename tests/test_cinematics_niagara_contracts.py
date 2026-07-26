"""Behavioral contracts for the cinematics and Niagara skill scripts."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load_script(name: str, relative_path: str):
    path = Path(__file__).resolve().parent.parent / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _render_unreal():
    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.MoviePipelineQueueSubsystem = type("MoviePipelineQueueSubsystem", (), {})
    unreal.MoviePipelineExecutorJob = type("MoviePipelineExecutorJob", (), {})
    unreal.MoviePipelineOutputSetting = type("MoviePipelineOutputSetting", (), {})
    unreal.MoviePipelineImageSequenceOutput_PNG = type("MoviePipelineImageSequenceOutput_PNG", (), {})
    unreal.MoviePipelineImageSequenceOutput_JPG = type("MoviePipelineImageSequenceOutput_JPG", (), {})
    unreal.MoviePipelineImageSequenceOutput_EXR = type("MoviePipelineImageSequenceOutput_EXR", (), {})
    unreal.SoftObjectPath = lambda value: value
    unreal.IntPoint = lambda x, y: (x, y)
    unreal.DirectoryPath = lambda value: value
    unreal.FrameRate = lambda numerator, denominator: types.SimpleNamespace(
        numerator=numerator,
        denominator=denominator,
    )

    sequence = MagicMock()
    sequence.get_display_rate.return_value = types.SimpleNamespace(numerator=24000, denominator=1001)
    unreal.load_asset = MagicMock(return_value=sequence)
    world = MagicMock()
    world.get_path_name.return_value = "/Game/Maps/TestMap.TestMap"
    unreal.EditorLevelLibrary = MagicMock()
    unreal.EditorLevelLibrary.get_editor_world.return_value = world

    output_setting = types.SimpleNamespace()
    format_setting = object()
    config = MagicMock()

    def find_or_add(setting_class):
        if setting_class is unreal.MoviePipelineOutputSetting:
            return output_setting
        if setting_class is unreal.MoviePipelineImageSequenceOutput_PNG:
            return format_setting
        return object()

    config.find_or_add_setting_by_class.side_effect = find_or_add
    job = types.SimpleNamespace(get_configuration=lambda: config)
    queue = MagicMock()
    queue.allocate_new_job.return_value = job
    subsystem = MagicMock()
    subsystem.get_queue.return_value = queue
    unreal.get_editor_subsystem = MagicMock(return_value=subsystem)
    return unreal, subsystem, queue, output_setting


def test_render_uses_real_output_setting_and_preserves_sequence_rate():
    unreal, _subsystem, _queue, output_setting = _render_unreal()
    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "render_sequence_to_movie",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/render_sequence_to_movie.py",
        )
        result = module.render_sequence_to_movie(
            sequence_path="/Game/Sequences/Test",
            output_path="C:/renders",
            output_format="png",
        )

    assert result["success"] is True
    assert output_setting.use_custom_frame_rate is False
    assert not hasattr(output_setting, "output_frame_rate")


def test_render_failure_removes_partial_job_and_returns_error():
    unreal, subsystem, queue, _output_setting = _render_unreal()
    subsystem.save_queue.side_effect = RuntimeError("queue save failed")
    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "render_sequence_to_movie_failure",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/render_sequence_to_movie.py",
        )
        result = module.render_sequence_to_movie(
            sequence_path="/Game/Sequences/Test",
            output_path="C:/renders",
        )

    assert result["success"] is False
    queue.delete_job.assert_called_once()


def test_niagara_asset_is_created_in_requested_package_path():
    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.does_directory_exist.return_value = True
    unreal.NiagaraSystemFactoryNew = MagicMock
    unreal.NiagaraSystem = type("NiagaraSystem", (), {})
    system = object()
    asset_tools = MagicMock()
    asset_tools.create_asset.return_value = system
    unreal.AssetToolsHelpers = MagicMock()
    unreal.AssetToolsHelpers.get_asset_tools.return_value = asset_tools

    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "create_niagara_system",
            "src/dcc_mcp_unreal/skills/unreal-niagara/scripts/create_niagara_system.py",
        )
        result = module.create_niagara_system(system_name="NS_Test", package_path="/Game/VFX")

    assert result["success"] is True
    assert asset_tools.create_asset.call_args.kwargs["package_path"] == "/Game/VFX"
    assert result["context"]["system_path"] == "/Game/VFX/NS_Test"


def test_niagara_template_request_fails_closed():
    module = _load_script(
        "create_niagara_system_template",
        "src/dcc_mcp_unreal/skills/unreal-niagara/scripts/create_niagara_system.py",
    )
    result = module.create_niagara_system(
        system_name="NS_Test",
        emitter_template="/Niagara/Templates/Fountain",
    )
    assert result["success"] is False
    assert "not supported" in result["message"].lower()
