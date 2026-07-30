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


def test_attach_actor_preserves_world_transform(monkeypatch):
    unreal = ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.AttachmentRule = SimpleNamespace(KEEP_WORLD="keep_world", KEEP_RELATIVE="keep_relative")
    child = MagicMock()
    parent = MagicMock()
    child.get_attach_parent_actor.return_value = None
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    import dcc_mcp_unreal.api

    monkeypatch.setattr(
        dcc_mcp_unreal.api,
        "find_level_actor",
        MagicMock(side_effect=lambda name: {"Gun": child, "TurntableRoot": parent}.get(name)),
    )

    result = _load(
        "attach_actor",
        "src/dcc_mcp_unreal/skills/unreal-actors/scripts/attach_actor.py",
    ).attach_actor(child_actor_name="Gun", parent_actor_name="TurntableRoot")

    assert result["success"] is True
    child.attach_to_actor.assert_called_once_with(
        parent,
        "",
        "keep_world",
        "keep_world",
        "keep_world",
        False,
    )


def test_get_actor_transform_reports_bounds(monkeypatch):
    actor = MagicMock()
    actor.get_actor_location.return_value = SimpleNamespace(x=1.0, y=2.0, z=3.0)
    actor.get_actor_rotation.return_value = SimpleNamespace(pitch=4.0, yaw=5.0, roll=6.0)
    actor.get_actor_scale3d.return_value = SimpleNamespace(x=1.0, y=1.0, z=1.0)
    actor.get_actor_bounds.return_value = (
        SimpleNamespace(x=10.0, y=20.0, z=30.0),
        SimpleNamespace(x=40.0, y=50.0, z=60.0),
    )
    import dcc_mcp_unreal.api

    monkeypatch.setattr(dcc_mcp_unreal.api, "find_level_actor", MagicMock(return_value=actor))
    result = _load(
        "get_actor_transform_bounds",
        "src/dcc_mcp_unreal/skills/unreal-actors/scripts/get_actor_transform.py",
    ).get_actor_transform(actor_name="Gun")

    assert result["context"]["bounds"]["origin"] == [10.0, 20.0, 30.0]


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


def test_configure_sky_light_assigns_hdr_texture_cube(monkeypatch):
    unreal = ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.TextureCube = type("TextureCube", (), {})
    unreal.SkyLightComponent = type("SkyLightComponent", (), {})
    unreal.SkyLightSourceType = SimpleNamespace(SLS_SPECIFIED_CUBEMAP="specified")
    cubemap = unreal.TextureCube()
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.load_asset.return_value = cubemap
    component = MagicMock()
    actor = MagicMock()
    actor.get_component_by_class.return_value = component
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    import dcc_mcp_unreal.api

    monkeypatch.setattr(dcc_mcp_unreal.api, "find_level_actor", MagicMock(return_value=actor))

    result = _load(
        "configure_sky_light",
        "src/dcc_mcp_unreal/skills/unreal-actors/scripts/configure_sky_light.py",
    ).configure_sky_light(
        actor_name="Lookdev_SkyLight",
        cubemap_path="/Game/Lookdev/T_Studio_HDRI",
        intensity_scale=1.25,
        source_cubemap_angle=390.0,
    )

    assert result["success"] is True
    assert result["context"]["source_cubemap_angle"] == 30.0
    component.set_editor_property.assert_any_call("source_type", "specified")
    component.set_editor_property.assert_any_call("cubemap", cubemap)
    component.set_editor_property.assert_any_call("intensity", 1.25)


def test_configure_light_sets_allowlisted_lookdev_properties(monkeypatch):
    unreal = ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.LightComponentBase = type("LightComponentBase", (), {})
    unreal.Color = lambda **values: SimpleNamespace(**values)
    component = MagicMock()
    actor = MagicMock()
    actor.get_component_by_class.return_value = component
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    import dcc_mcp_unreal.api

    monkeypatch.setattr(dcc_mcp_unreal.api, "find_level_actor", MagicMock(return_value=actor))

    result = _load(
        "configure_light",
        "src/dcc_mcp_unreal/skills/unreal-actors/scripts/configure_light.py",
    ).configure_light(
        actor_name="Lookdev_Key",
        intensity=18000,
        color_r=1.0,
        color_g=0.8,
        color_b=0.65,
        source_radius=35,
    )

    assert result["success"] is True
    component.set_editor_property.assert_any_call("intensity", 18000.0)
    component.set_editor_property.assert_any_call("source_radius", 35.0)
    color_call = next(call for call in component.set_editor_property.call_args_list if call.args[0] == "light_color")
    assert color_call.args[1].r == 255


def test_configure_camera_exposure_disables_eye_adaptation(monkeypatch):
    unreal = ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.CameraComponent = type("CameraComponent", (), {})
    unreal.AutoExposureMethod = SimpleNamespace(AEM_MANUAL="manual")
    settings = MagicMock()
    component = MagicMock()
    component.get_editor_property.return_value = settings
    actor = MagicMock()
    actor.get_component_by_class.return_value = component
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    import dcc_mcp_unreal.api

    monkeypatch.setattr(dcc_mcp_unreal.api, "find_level_actor", MagicMock(return_value=actor))

    result = _load(
        "configure_camera_exposure",
        "src/dcc_mcp_unreal/skills/unreal-actors/scripts/configure_camera_exposure.py",
    ).configure_camera_exposure(actor_name="Lookdev_Camera", exposure_compensation=-2.0)

    assert result["success"] is True
    settings.set_editor_property.assert_any_call("auto_exposure_method", "manual")
    settings.set_editor_property.assert_any_call("auto_exposure_apply_physical_camera_exposure", False)
    settings.set_editor_property.assert_any_call("auto_exposure_bias", -2.0)
    component.set_editor_property.assert_called_once_with("post_process_settings", settings)


def test_create_ocio_configuration_persists_valid_display_transform(monkeypatch):
    unreal = ModuleType("unreal")
    unreal.log = MagicMock()

    class OpenColorIOConfiguration:
        def __init__(self):
            self.properties = {}

        def set_editor_property(self, name, value):
            self.properties[name] = value

        def get_editor_property(self, name):
            return self.properties[name]

        def reload_existing_colorspaces(self, _force):
            pass

    asset = OpenColorIOConfiguration()
    unreal.OpenColorIOConfiguration = OpenColorIOConfiguration
    unreal.OpenColorIOConfigurationFactoryNew = type("OpenColorIOConfigurationFactoryNew", (), {})
    unreal.OpenColorIOColorSpace = lambda **values: SimpleNamespace(**values)
    unreal.OpenColorIODisplayView = lambda **values: SimpleNamespace(**values)
    unreal.OpenColorIOColorConversionSettings = lambda **values: SimpleNamespace(**values)
    unreal.OpenColorIODisplayConfiguration = lambda **values: SimpleNamespace(**values)
    unreal.OpenColorIOViewTransformDirection = SimpleNamespace(FORWARD="forward")
    unreal.OpenColorIOEditorBlueprintLibrary = MagicMock()
    unreal.FilePath = lambda **values: SimpleNamespace(**values)
    unreal.EditorAssetLibrary = MagicMock()
    unreal.EditorAssetLibrary.load_asset.return_value = None
    unreal.EditorAssetLibrary.save_loaded_asset.return_value = True
    asset_tools = MagicMock()
    asset_tools.create_asset.return_value = asset
    unreal.AssetToolsHelpers = SimpleNamespace(get_asset_tools=lambda: asset_tools)
    monkeypatch.setitem(sys.modules, "unreal", unreal)

    result = _load(
        "create_ocio_configuration",
        "src/dcc_mcp_unreal/skills/unreal-assets/scripts/create_ocio_configuration.py",
    ).create_ocio_configuration(
        asset_path="/Game/Drawcall557/Color/OCIO_ACES13_CG",
        configuration_path="ocio://cg-config-v2.2.0_aces-v1.3_ocio-v2.4",
        apply_to_active_viewport=True,
    )

    assert result["success"] is True
    assert result["context"]["transform_valid"] is True
    assert result["context"]["active_viewport_configured"] is True
    assert asset.properties["configuration_file"].file_path.startswith("ocio://cg-config-v2.2.0")
    unreal.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(asset, only_if_is_dirty=False)
    unreal.OpenColorIOEditorBlueprintLibrary.set_active_viewport_configuration.assert_called_once()


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


def test_transform_keyframes_support_linear_interpolation():
    script = (ROOT / "src/dcc_mcp_unreal/skills/unreal-cinematics/scripts/add_transform_keyframe.py").read_text(
        encoding="utf-8"
    )
    tools = (ROOT / "src/dcc_mcp_unreal/skills/unreal-cinematics/tools.yaml").read_text(encoding="utf-8")

    assert 'interpolation: str = "default"' in script
    assert "RichCurveInterpMode.RCIM_LINEAR" in script
    assert "key.set_interpolation_mode(interpolation_mode)" in script
    assert "enum: [default, linear, constant]" in tools
