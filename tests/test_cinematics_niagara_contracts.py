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
    unreal.LevelSequence = type("LevelSequence", (), {})
    unreal.MoviePipelineQueueSubsystem = type("MoviePipelineQueueSubsystem", (), {})
    unreal.MoviePipelineExecutorJob = type("MoviePipelineExecutorJob", (), {})
    unreal.MoviePipelineOutputSetting = type("MoviePipelineOutputSetting", (), {})
    unreal.MoviePipelineImageSequenceOutput_PNG = type("MoviePipelineImageSequenceOutput_PNG", (), {})
    unreal.MoviePipelineImageSequenceOutput_JPG = type("MoviePipelineImageSequenceOutput_JPG", (), {})
    unreal.MoviePipelineImageSequenceOutput_EXR = type("MoviePipelineImageSequenceOutput_EXR", (), {})
    unreal.MoviePipelineDeferredPassBase = type("MoviePipelineDeferredPassBase", (), {})
    unreal.MoviePipelineAntiAliasingSetting = type("MoviePipelineAntiAliasingSetting", (), {})
    unreal.MoviePipelineGameOverrideSetting = type("MoviePipelineGameOverrideSetting", (), {})
    unreal.MoviePipelineColorSetting = type("MoviePipelineColorSetting", (), {})
    unreal.AntiAliasingMethod = types.SimpleNamespace(AAM_TSR="tsr")
    unreal.MoviePipelineTextureStreamingMethod = types.SimpleNamespace(DISABLED="disabled")
    unreal.OpenColorIOViewTransformDirection = types.SimpleNamespace(FORWARD="forward")
    unreal.SoftObjectPath = lambda value: value
    unreal.IntPoint = lambda x, y: (x, y)
    unreal.DirectoryPath = lambda value: value
    unreal.FilePath = lambda **values: types.SimpleNamespace(**values)
    unreal.OpenColorIOColorSpace = lambda **values: types.SimpleNamespace(**values)
    unreal.OpenColorIODisplayView = lambda **values: types.SimpleNamespace(**values)
    unreal.OpenColorIOColorConversionSettings = lambda **values: types.SimpleNamespace(**values)
    unreal.OpenColorIODisplayConfiguration = lambda **values: types.SimpleNamespace(**values)

    class OpenColorIOConfiguration:
        def __init__(self, **_values):
            self.properties = {}
            self.reloaded = False

        def set_editor_property(self, name, value):
            self.properties[name] = value

        def get_editor_property(self, name):
            return self.properties[name]

        def reload_existing_colorspaces(self, force):
            self.reloaded = force

    unreal.OpenColorIOConfiguration = OpenColorIOConfiguration
    unreal.FrameRate = lambda numerator, denominator: types.SimpleNamespace(
        numerator=numerator,
        denominator=denominator,
    )

    sequence = unreal.LevelSequence()
    sequence.get_display_rate = MagicMock()
    sequence.get_display_rate.return_value = types.SimpleNamespace(numerator=24000, denominator=1001)
    unreal.load_asset = MagicMock(return_value=sequence)
    world = MagicMock()
    world.get_path_name.return_value = "/Game/Maps/TestMap.TestMap"
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.does_asset_exist.return_value = True
    unreal.EditorLevelLibrary = MagicMock()
    unreal.EditorLevelLibrary.get_editor_world.return_value = world

    output_setting = types.SimpleNamespace()
    format_setting = object()
    anti_aliasing = types.SimpleNamespace()
    game_override = types.SimpleNamespace()
    color_setting = types.SimpleNamespace()
    unreal._test_color_setting = color_setting
    config = MagicMock()

    def find_or_add(setting_class):
        if setting_class is unreal.MoviePipelineOutputSetting:
            return output_setting
        if setting_class is unreal.MoviePipelineImageSequenceOutput_PNG:
            return format_setting
        if setting_class is unreal.MoviePipelineAntiAliasingSetting:
            return anti_aliasing
        if setting_class is unreal.MoviePipelineGameOverrideSetting:
            return game_override
        if setting_class is unreal.MoviePipelineColorSetting:
            return color_setting
        return object()

    config.find_or_add_setting_by_class.side_effect = find_or_add
    job = types.SimpleNamespace(get_configuration=lambda: config)
    queue = MagicMock()
    queue.allocate_new_job.return_value = job
    queue.get_jobs.return_value = [job]
    subsystem = MagicMock()
    subsystem.get_queue.return_value = queue
    unreal.get_editor_subsystem = MagicMock(return_value=subsystem)
    return unreal, subsystem, queue, output_setting


def test_queue_uses_real_output_setting_and_preserves_sequence_rate():
    unreal, subsystem, _queue, output_setting = _render_unreal()
    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "queue_sequence_render",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/queue_sequence_render.py",
        )
        result = module.queue_sequence_render(
            sequence_path="/Game/Sequences/Test",
            output_path="C:/renders",
            output_format="png",
        )

    assert result["success"] is True
    assert output_setting.use_custom_frame_rate is False
    assert not hasattr(output_setting, "output_frame_rate")
    assert result["context"]["job_status"] == "queued_not_started"
    assert result["context"]["render_started"] is False
    assert result["context"]["map_path"] == "/Game/Maps/TestMap"
    assert result["context"]["temporal_samples"] == 8
    subsystem.save_queue.assert_not_called()


def test_queue_configures_ocio_color_output(tmp_path):
    ocio_path = tmp_path / "config.ocio"
    ocio_path.write_text("ocio_profile_version: 2", encoding="utf-8")
    unreal, _subsystem, _queue, _output_setting = _render_unreal()
    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "queue_sequence_render_ocio",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/queue_sequence_render.py",
        )
        result = module.queue_sequence_render(
            sequence_path="/Game/Sequences/Test",
            output_path="C:/renders",
            ocio_config_path=str(ocio_path),
        )

    assert result["success"] is True
    assert result["context"]["ocio_enabled"] is True
    assert unreal._test_color_setting.disable_tone_curve is True
    assert unreal._test_color_setting.ocio_configuration.is_enabled is True
    assert (
        unreal._test_color_setting.ocio_configuration.color_configuration.source_color_space.color_space_name
        == "ACEScg"
    )


def test_queue_can_clear_existing_jobs_before_adding_render():
    unreal, _subsystem, queue, _output_setting = _render_unreal()
    previous_job = object()
    queue.get_jobs.side_effect = [[previous_job], [queue.allocate_new_job.return_value]]
    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "queue_sequence_render_clear",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/queue_sequence_render.py",
        )
        result = module.queue_sequence_render(
            sequence_path="/Game/Sequences/Test",
            output_path="C:/renders",
            clear_existing_jobs=True,
        )

    assert result["success"] is True
    assert result["context"]["cleared_jobs"] == 1
    queue.delete_job.assert_called_once_with(previous_job)


def test_queue_rejects_ocio_transform_missing_after_reload(tmp_path):
    ocio_path = tmp_path / "config.ocio"
    ocio_path.write_text("ocio_profile_version: 2", encoding="utf-8")
    unreal, _subsystem, queue, _output_setting = _render_unreal()

    def drop_requested_transforms(config, _force):
        config.properties["desired_color_spaces"] = []
        config.properties["desired_display_views"] = []

    unreal.OpenColorIOConfiguration.reload_existing_colorspaces = drop_requested_transforms
    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "queue_sequence_render_invalid_ocio",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/queue_sequence_render.py",
        )
        result = module.queue_sequence_render(
            sequence_path="/Game/Sequences/Test",
            output_path="C:/renders",
            ocio_config_path=str(ocio_path),
        )

    assert result["success"] is False
    assert result["message"] == "Invalid OCIO transform"
    queue.delete_job.assert_called_once()


def test_queue_absolute_path_validation_is_agent_platform_independent():
    module = _load_script(
        "queue_sequence_render_path_contract",
        "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/queue_sequence_render.py",
    )

    assert module._is_absolute_output_path("C:/renders") is True
    assert module._is_absolute_output_path(r"\\server\share\renders") is True
    assert module._is_absolute_output_path("/var/tmp/renders") is True
    assert module._is_absolute_output_path("renders/output") is False
    assert module._is_absolute_output_path("C:renders") is False


def test_queue_failure_removes_partial_job_and_returns_error():
    unreal, _subsystem, queue, _output_setting = _render_unreal()
    queue.get_jobs.side_effect = RuntimeError("queue verification failed")
    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "queue_sequence_render_failure",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/queue_sequence_render.py",
        )
        result = module.queue_sequence_render(
            sequence_path="/Game/Sequences/Test",
            output_path="C:/renders",
        )

    assert result["success"] is False
    queue.delete_job.assert_called_once()


def test_queue_rejects_unsaved_editor_level_before_allocating_job():
    unreal, _subsystem, queue, _output_setting = _render_unreal()
    unreal.EditorLevelLibrary.get_editor_world.return_value.get_path_name.return_value = "/Temp/Untitled_1.Untitled_1"
    unreal.EditorAssetLibrary.does_asset_exist.return_value = False
    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "queue_sequence_render_unsaved_map",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/queue_sequence_render.py",
        )
        result = module.queue_sequence_render(
            sequence_path="/Game/Sequences/Test",
            output_path="C:/renders",
        )

    assert result["success"] is False
    assert result["message"] == "Current level is not saved"
    queue.allocate_new_job.assert_not_called()


def test_queue_rejects_unsafe_lumen_atlas_before_allocating_job(tmp_path):
    unreal, _subsystem, queue, _output_setting = _render_unreal()
    config_path = tmp_path / "DefaultEngine.ini"
    config_path.write_text(
        "[ConsoleVariables]\nr.LumenScene.SurfaceCache.AtlasSize=16384\n",
        encoding="utf-8",
    )
    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "queue_sequence_render_unsafe_lumen",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/queue_sequence_render.py",
        )
        module.project_config_path = lambda: config_path
        result = module.queue_sequence_render(
            sequence_path="/Game/Sequences/Test",
            output_path="C:/renders",
        )

    assert result["success"] is False
    assert result["message"] == "Unsafe Lumen renderer config"
    queue.allocate_new_job.assert_not_called()


def test_queue_fails_cleanly_when_movie_render_queue_plugin_is_disabled():
    unreal, _subsystem, queue, _output_setting = _render_unreal()
    del unreal.MoviePipelineQueueSubsystem
    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "queue_sequence_render_plugin_disabled",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/queue_sequence_render.py",
        )
        result = module.queue_sequence_render(
            sequence_path="/Game/Sequences/Test",
            output_path="C:/renders",
        )

    assert result["success"] is False
    assert result["message"] == "Movie Render Queue unavailable"
    queue.allocate_new_job.assert_not_called()


def test_cancel_render_uses_active_executor():
    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.MoviePipelineQueueSubsystem = type("MoviePipelineQueueSubsystem", (), {})
    executor = MagicMock()
    subsystem = MagicMock()
    subsystem.get_active_executor.return_value = executor
    subsystem.is_rendering.return_value = True
    unreal.get_editor_subsystem = MagicMock(return_value=subsystem)

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script(
            "cancel_queued_render",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/cancel_queued_render.py",
        ).cancel_queued_render()

    assert result["success"] is True
    assert result["context"]["cancellation_requested"] is True
    executor.cancel_all_jobs.assert_called_once_with()


def test_create_level_sequence_uses_requested_package_and_fractional_rate():
    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.LevelSequence = type("LevelSequence", (), {})
    sequence = unreal.LevelSequence()
    sequence.set_display_rate = MagicMock()
    unreal.LevelSequenceFactoryNew = MagicMock
    unreal.FrameRate = lambda numerator, denominator: types.SimpleNamespace(
        numerator=numerator,
        denominator=denominator,
    )
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.does_asset_exist.return_value = False
    unreal.EditorAssetLibrary.does_directory_exist.return_value = True
    unreal.EditorAssetLibrary.save_loaded_asset.return_value = True
    unreal.load_asset = MagicMock(return_value=sequence)
    asset_tools = MagicMock()
    asset_tools.create_asset.return_value = sequence
    unreal.AssetToolsHelpers = MagicMock()
    unreal.AssetToolsHelpers.get_asset_tools.return_value = asset_tools

    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "create_level_sequence_contract",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/create_level_sequence.py",
        )
        result = module.create_level_sequence(
            sequence_name="LS_Test",
            package_path="/Game/Cinematics",
            frame_rate=24000 / 1001,
        )

    assert result["success"] is True
    assert asset_tools.create_asset.call_args.kwargs["package_path"] == "/Game/Cinematics"
    assert result["context"]["sequence_path"] == "/Game/Cinematics/LS_Test"
    rate = sequence.set_display_rate.call_args.args[0]
    assert (rate.numerator, rate.denominator) == (24000, 1001)


def test_playback_range_uses_frame_rate_denominator_and_fails_closed():
    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()
    sequence = MagicMock()
    sequence.get_display_rate.return_value = types.SimpleNamespace(numerator=24000, denominator=1001)
    state = {"start": 0, "end": 0}
    sequence.set_playback_start.side_effect = lambda value: state.__setitem__("start", value)
    sequence.set_playback_end.side_effect = lambda value: state.__setitem__("end", value)
    sequence.get_playback_start.side_effect = lambda: state["start"]
    sequence.get_playback_end.side_effect = lambda: state["end"]
    unreal.load_asset = MagicMock(return_value=sequence)
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.save_loaded_asset.return_value = True

    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "set_playback_range_contract",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/set_playback_range.py",
        )
        result = module.set_playback_range(
            sequence_path="/Game/Cinematics/LS_Test",
            start_time=1.001,
            end_time=2.002,
        )

    assert result["success"] is True
    assert state == {"start": 24, "end": 48}

    sequence.set_playback_start.side_effect = RuntimeError("write failed")
    with patch.dict(sys.modules, {"unreal": unreal}):
        result = module.set_playback_range(
            sequence_path="/Game/Cinematics/LS_Test",
            start_time=0.0,
            end_time=1.0,
        )
    assert result["success"] is False


def test_camera_cut_uses_sequence_binding_id():
    import dcc_mcp_unreal.api as api_module

    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()

    class CameraCutTrack:
        pass

    class ObjectBindingId:
        def set_editor_property(self, name, value):
            setattr(self, name, value)

    unreal.MovieSceneCameraCutTrack = CameraCutTrack
    unreal.MovieSceneObjectBindingID = ObjectBindingId

    section = MagicMock()
    track = CameraCutTrack()
    track.add_section = MagicMock(return_value=section)
    binding_guid = object()
    binding = MagicMock()
    binding.get_id.return_value = binding_guid
    sequence = MagicMock()
    sequence.get_tracks.return_value = []
    sequence.add_track.return_value = track
    sequence.add_possessable.return_value = binding
    sequence.get_binding_id.return_value = binding_guid
    sequence.get_display_rate.return_value = types.SimpleNamespace(numerator=24000, denominator=1001)
    unreal.load_asset = MagicMock(return_value=sequence)
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.save_loaded_asset.return_value = True

    with (
        patch.dict(sys.modules, {"unreal": unreal}),
        patch.object(api_module, "find_level_actor", return_value=object(), create=True),
    ):
        module = _load_script(
            "add_camera_cut_track_contract",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/add_camera_cut_track.py",
        )
        result = module.add_camera_cut_track(
            sequence_path="/Game/Cinematics/LS_Test",
            camera_name="CameraActor",
            start_time=1.001,
            end_time=2.002,
        )

    assert result["success"] is True
    section.set_camera_binding_id.assert_called_once_with(binding_guid)
    section.set_range.assert_called_once_with(24, 48)


def test_camera_cut_reuses_existing_named_binding():
    import dcc_mcp_unreal.api as api_module

    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()

    class CameraCutTrack:
        pass

    class ObjectBindingId:
        def set_editor_property(self, name, value):
            setattr(self, name, value)

    unreal.MovieSceneCameraCutTrack = CameraCutTrack
    unreal.MovieSceneObjectBindingID = ObjectBindingId
    section = MagicMock()
    track = CameraCutTrack()
    track.add_section = MagicMock(return_value=section)
    binding = MagicMock()
    binding.get_display_name.return_value = "HeroCamera"
    binding.get_id.return_value = object()
    sequence = MagicMock()
    sequence.get_tracks.return_value = [track]
    sequence.get_bindings.return_value = [binding]
    sequence.get_display_rate.return_value = types.SimpleNamespace(numerator=30, denominator=1)
    unreal.load_asset = MagicMock(return_value=sequence)
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.save_loaded_asset.return_value = True

    with (
        patch.dict(sys.modules, {"unreal": unreal}),
        patch.object(api_module, "find_level_actor", return_value=object(), create=True),
    ):
        module = _load_script(
            "add_camera_cut_reuse_contract",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/add_camera_cut_track.py",
        )
        result = module.add_camera_cut_track(
            sequence_path="/Game/Cinematics/LS_Test",
            camera_name="CameraActor",
            binding_name="HeroCamera",
            start_time=0.0,
            end_time=1.0,
        )

    assert result["success"] is True
    sequence.add_possessable.assert_not_called()
    binding_id = section.set_camera_binding_id.call_args.args[0]
    assert binding_id.guid is binding.get_id.return_value


def test_sequence_info_normalizes_unreal_text_and_detects_camera_track_by_type():
    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()

    class UnrealText:
        def __init__(self, value):
            self.value = value

        def __str__(self):
            return self.value

    class CameraCutTrack:
        def get_display_name(self):
            return UnrealText("Localized camera cuts")

    unreal.MovieSceneCameraCutTrack = CameraCutTrack
    transform_track = MagicMock()
    transform_track.get_display_name.return_value = UnrealText("Transform")
    binding = MagicMock()
    binding.get_display_name.return_value = UnrealText("BoundActor")
    binding.get_id.return_value = "binding-guid"
    binding.get_tracks.return_value = [transform_track]
    sequence = MagicMock()
    sequence.get_display_rate.return_value = types.SimpleNamespace(numerator=24000, denominator=1001)
    sequence.get_playback_start.return_value = 24
    sequence.get_playback_end.return_value = 48
    sequence.get_bindings.return_value = [binding]
    sequence.get_tracks.return_value = [CameraCutTrack()]
    unreal.load_asset = MagicMock(return_value=sequence)

    with patch.dict(sys.modules, {"unreal": unreal}):
        module = _load_script(
            "get_sequence_info_contract",
            "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/get_sequence_info.py",
        )
        result = module.get_sequence_info(sequence_path="/Game/Cinematics/LS_Test")

    assert result["success"] is True
    assert result["context"]["bindings"][0]["name"] == "BoundActor"
    assert result["context"]["bindings"][0]["tracks"] == ["Transform"]
    assert result["context"]["master_tracks"] == ["Localized camera cuts"]
    assert result["context"]["has_camera_cut_track"] is True


def test_cinematics_contract_exposes_queue_not_render_success():
    root = Path(__file__).resolve().parents[1]
    tools = (root / "src/dcc_mcp_unreal/skills/unreal-cinematics/tools.yaml").read_text(encoding="utf-8")
    skill = (root / "src/dcc_mcp_unreal/skills/unreal-cinematics/SKILL.md").read_text(encoding="utf-8")

    assert "queue_sequence_render" in tools
    assert "render_sequence_to_movie" not in tools
    assert "does not start" in tools and "rendering" in tools
    assert "queue_sequence_render" in skill


def test_cinematics_and_niagara_skill_contracts_validate():
    from dcc_mcp_core import validate_skill

    skills_root = Path(__file__).resolve().parents[1] / "src/dcc_mcp_unreal/skills"
    for skill_name in ("unreal-cinematics", "unreal-niagara"):
        report = validate_skill(str(skills_root / skill_name))
        assert not report.has_errors, report.issues


def test_niagara_asset_is_created_in_requested_package_path():
    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.does_directory_exist.return_value = True
    unreal.EditorAssetLibrary.does_asset_exist.return_value = False
    unreal.EditorAssetLibrary.save_loaded_asset.return_value = True
    unreal.NiagaraSystemFactoryNew = MagicMock
    unreal.NiagaraSystem = type("NiagaraSystem", (), {})
    system = unreal.NiagaraSystem()
    asset_tools = MagicMock()
    asset_tools.create_asset.return_value = system
    unreal.AssetToolsHelpers = MagicMock()
    unreal.AssetToolsHelpers.get_asset_tools.return_value = asset_tools
    unreal.load_asset = MagicMock(return_value=system)

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
