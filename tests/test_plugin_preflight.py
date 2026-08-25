from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from dcc_mcp_unreal.skill_runner import run_skill_script

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_SCRIPT = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-automation" / "scripts" / "preflight_plugins.py"


def test_static_groom_preflight_reports_exact_missing_plugin() -> None:
    unreal = types.ModuleType("unreal")
    unreal.log = lambda _message: None
    unreal.DccMcpAutomationLibrary = types.SimpleNamespace(
        get_enabled_plugin_names=lambda: ["HairStrands", "PythonScriptPlugin"]
    )

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = run_skill_script(
            str(PREFLIGHT_SCRIPT),
            {"capability": "static_groom_import"},
        )

    assert result["success"] is True
    assert result["context"]["required_plugins"] == ["HairStrands", "AlembicHairImporter"]
    assert result["context"]["enabled_plugins"] == ["HairStrands"]
    assert result["context"]["missing_plugins"] == ["AlembicHairImporter"]
    assert result["context"]["ready"] is False
    assert result["context"]["next_action"] == {
        "action": "restart_editor",
        "arguments": ["-EnablePlugins=HairStrands,AlembicHairImporter"],
        "retry_tool": "unreal_automation__preflight_plugins",
        "retry_arguments": {"capability": "static_groom_import"},
    }


def test_static_groom_fails_before_creating_an_import_task_when_plugin_is_missing(tmp_path: Path) -> None:
    helper_path = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-assets" / "scripts" / "_groom_import.py"
    helper_spec = importlib.util.spec_from_file_location("_groom_import", helper_path)
    assert helper_spec and helper_spec.loader
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)

    unreal = types.ModuleType("unreal")
    unreal.DccMcpAutomationLibrary = types.SimpleNamespace(get_enabled_plugin_names=lambda: ["HairStrands"])
    unreal.AssetImportTask = MagicMock(side_effect=AssertionError("mutation must not start"))
    source = tmp_path / "hair.abc"
    source.write_bytes(b"abc")
    script = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-assets" / "scripts" / "import_static_groom.py"

    with patch.dict(sys.modules, {"_groom_import": helper, "unreal": unreal}):
        spec = importlib.util.spec_from_file_location("missing_groom_plugin", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.import_static_groom(source_path=str(source))

    assert result["success"] is False
    assert result["context"]["missing_plugins"] == ["AlembicHairImporter"]
    assert result["context"]["required_plugins"] == ["HairStrands", "AlembicHairImporter"]
    unreal.AssetImportTask.assert_not_called()


def test_usd_import_fails_before_creating_an_import_task_when_plugin_is_missing(tmp_path: Path) -> None:
    helper_path = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-assets" / "scripts" / "_asset_import.py"
    helper_spec = importlib.util.spec_from_file_location("_asset_import", helper_path)
    assert helper_spec and helper_spec.loader
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)

    unreal = types.ModuleType("unreal")
    unreal.DccMcpAutomationLibrary = types.SimpleNamespace(get_enabled_plugin_names=lambda: ["HairStrands"])
    unreal.AssetImportTask = MagicMock(side_effect=AssertionError("mutation must not start"))
    source = tmp_path / "stage.usda"
    source.write_text("#usda 1.0", encoding="utf-8")
    script = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-assets" / "scripts" / "import_asset.py"

    with patch.dict(sys.modules, {"_asset_import": helper, "unreal": unreal}):
        spec = importlib.util.spec_from_file_location("missing_usd_plugin", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.import_asset(source_path=str(source))

    assert result["success"] is False
    assert result["context"]["missing_plugins"] == ["USDImporter"]
    assert result["context"]["required_plugins"] == ["USDImporter"]
    unreal.AssetImportTask.assert_not_called()


def test_start_render_fails_before_mrq_dispatch_when_plugin_is_missing() -> None:
    unreal = types.ModuleType("unreal")
    unreal.DccMcpAutomationLibrary = types.SimpleNamespace(get_enabled_plugin_names=lambda: ["USDImporter"])
    unreal.get_editor_subsystem = MagicMock(side_effect=AssertionError("dispatch must not start"))
    unreal.SystemLibrary = types.SimpleNamespace(execute_console_command=MagicMock())
    script = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-cinematics" / "scripts" / "start_queued_render.py"

    with patch.dict(sys.modules, {"unreal": unreal}):
        spec = importlib.util.spec_from_file_location("missing_mrq_plugin", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.start_queued_render()

    assert result["success"] is False
    assert result["context"]["missing_plugins"] == ["MovieRenderPipeline"]
    assert result["context"]["required_plugins"] == ["MovieRenderPipeline"]
    unreal.get_editor_subsystem.assert_not_called()
    unreal.SystemLibrary.execute_console_command.assert_not_called()


def test_native_bridge_exposes_read_only_enabled_plugin_names() -> None:
    header = (
        ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Public" / "DccMcpAutomationLibrary.h"
    ).read_text(encoding="utf-8")
    implementation = (
        ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpAutomationLibrary.cpp"
    ).read_text(encoding="utf-8")

    assert "static TArray<FString> GetEnabledPluginNames();" in header
    assert "IPluginManager::Get().GetEnabledPlugins()" in implementation


def test_native_bridge_injects_ue5_axis_input_as_a_sampled_axis_event() -> None:
    implementation = (
        ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpAutomationLibrary.cpp"
    ).read_text(encoding="utf-8")

    assert "if (Event == IE_Axis)" in implementation
    assert "FInputKeyParams(Key, static_cast<double>(Value), AxisDeltaTime, 1, false, InputDevice)" in implementation


def test_native_bridge_routes_pre_player_pie_key_events_through_slate() -> None:
    implementation = (
        ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpAutomationLibrary.cpp"
    ).read_text(encoding="utf-8")
    build_rules = (ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "DccMcpUnreal.Build.cs").read_text(
        encoding="utf-8"
    )

    assert "if (PlayerController)" in implementation
    assert "return InjectSlatePieKey(Key, bPressed);" in implementation
    assert "GEditor->PlayWorld" in implementation
    assert "!GEditor->GetPIEViewport()" not in implementation
    assert "ProcessKeyDownEvent" in implementation
    assert "ProcessMouseButtonDownEvent" in implementation
    assert "ClickPiePointerButton" in implementation
    assert "GetPositionInScreen" in implementation
    assert "GetSizeInScreen" in implementation
    assert "LocateWindowUnderMouse" in implementation
    assert "RoutePointerMoveEvent" in implementation
    assert "ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 26" in implementation
    assert '"Slate"' in build_rules
    assert '"SlateCore"' in build_rules


def test_native_bridge_resolves_player_after_pie_world_transition() -> None:
    implementation = (
        ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpAutomationLibrary.cpp"
    ).read_text(encoding="utf-8")

    assert '#include "Engine/Engine.h"' in implementation
    assert "GEngine->GetWorldContexts()" in implementation
    assert "WorldContext.WorldType != EWorldType::PIE" in implementation
    assert "WorldContext.World()" in implementation
    assert "bool HasPieWorld()" in implementation
    assert "IsInGameThread() && HasPieWorld() && FSlateApplication::IsInitialized()" in implementation
    assert "GetFirstLocalPlayerController" in implementation
    assert "WorldContext.OwningGameInstance" in implementation
    assert "TObjectIterator<APlayerController>" in implementation
    assert "PlayerController->IsLocalController()" in implementation


def test_native_bridge_acknowledges_axis_only_digital_key_delivery() -> None:
    implementation = (
        ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpAutomationLibrary.cpp"
    ).read_text(encoding="utf-8")
    build_rules = (ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "DccMcpUnreal.Build.cs").read_text(
        encoding="utf-8"
    )

    assert '#include "GenericPlatform/GenericPlatformInputDeviceMapper.h"' in implementation
    assert "IPlatformInputDeviceMapper::Get().GetPrimaryInputDeviceForUser(" in implementation
    assert "PlayerController->GetPlatformUserId()" in implementation
    assert "if (!PlayerController || !PlayerController->PlayerInput)" in implementation
    assert "FInputKeyParams(Key, Event, static_cast<double>(Value), false, InputDevice)" in implementation
    assert "whether the key state was updated" in implementation
    assert "return true;" in implementation
    assert '"ApplicationCore"' in build_rules


def test_queue_render_fails_before_loading_assets_when_plugin_is_missing(tmp_path: Path) -> None:
    unreal = types.ModuleType("unreal")
    unreal.DccMcpAutomationLibrary = types.SimpleNamespace(get_enabled_plugin_names=lambda: [])
    unreal.load_asset = MagicMock(side_effect=AssertionError("asset dispatch must not start"))
    script = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-cinematics" / "scripts" / "queue_sequence_render.py"

    with patch.dict(sys.modules, {"unreal": unreal}):
        spec = importlib.util.spec_from_file_location("missing_queue_plugin", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.queue_sequence_render(
            sequence_path="/Game/Cinematics/LS_Shot",
            output_path=str(tmp_path.resolve()),
        )

    assert result["success"] is False
    assert result["context"]["missing_plugins"] == ["MovieRenderPipeline"]
    unreal.load_asset.assert_not_called()


@pytest.mark.parametrize(
    ("script_name", "function_name"),
    [
        ("get_render_status.py", "get_render_status"),
        ("cancel_queued_render.py", "cancel_queued_render"),
    ],
)
def test_mrq_control_tools_fail_before_subsystem_dispatch_when_plugin_is_missing(
    script_name: str,
    function_name: str,
) -> None:
    unreal = types.ModuleType("unreal")
    unreal.DccMcpAutomationLibrary = types.SimpleNamespace(get_enabled_plugin_names=lambda: [])
    unreal.get_editor_subsystem = MagicMock(side_effect=AssertionError("dispatch must not start"))
    script = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-cinematics" / "scripts" / script_name

    with patch.dict(sys.modules, {"unreal": unreal}):
        spec = importlib.util.spec_from_file_location("missing_" + function_name, script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = getattr(module, function_name)()

    assert result["success"] is False
    assert result["context"]["missing_plugins"] == ["MovieRenderPipeline"]
    unreal.get_editor_subsystem.assert_not_called()


@pytest.mark.parametrize(
    ("script_name", "function_name"),
    [
        ("render_audi_phase_stills.py", "render_audi_phase_stills"),
        ("render_audi_rain_film.py", "render_audi_rain_film"),
    ],
)
def test_automotive_mrq_tools_fail_before_main_thread_dispatch_when_plugin_is_missing(
    script_name: str,
    function_name: str,
) -> None:
    scripts = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-automotive-rain-film" / "scripts"
    loaded_helpers = {}
    for helper_name in ("_automotive_common", "_movie_render"):
        helper_spec = importlib.util.spec_from_file_location(
            helper_name,
            scripts / (helper_name + ".py"),
        )
        assert helper_spec and helper_spec.loader
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)
        loaded_helpers[helper_name] = helper

    unreal = types.ModuleType("unreal")
    unreal.DccMcpAutomationLibrary = types.SimpleNamespace(get_enabled_plugin_names=lambda: [])
    dispatcher = MagicMock(side_effect=AssertionError("main-thread dispatch must not start"))
    import dcc_mcp_unreal.server as server_module

    previous_server = server_module._server_instance
    server_module._server_instance = types.SimpleNamespace(
        _main_thread_dispatcher=types.SimpleNamespace(dispatch_callable=dispatcher)
    )
    try:
        with patch.dict(sys.modules, {**loaded_helpers, "unreal": unreal}):
            spec = importlib.util.spec_from_file_location(
                "missing_automotive_" + function_name,
                scripts / script_name,
            )
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = getattr(module, function_name)()
    finally:
        server_module._server_instance = previous_server

    assert result["success"] is False
    assert result["context"]["missing_plugins"] == ["MovieRenderPipeline"]
    dispatcher.assert_not_called()


def test_queue_render_reports_active_mrq_before_asset_or_queue_mutation(tmp_path: Path) -> None:
    unreal = types.ModuleType("unreal")
    unreal.DccMcpAutomationLibrary = types.SimpleNamespace(get_enabled_plugin_names=lambda: ["MovieRenderPipeline"])
    unreal.MoviePipelineQueueSubsystem = type("MoviePipelineQueueSubsystem", (), {})
    unreal.LevelEditorSubsystem = type("LevelEditorSubsystem", (), {})
    unreal.EditorLevelLibrary = types.SimpleNamespace(get_editor_world=lambda: None)
    mrq_subsystem = types.SimpleNamespace(is_rendering=lambda: True)
    unreal.get_editor_subsystem = lambda cls: mrq_subsystem if cls is unreal.MoviePipelineQueueSubsystem else None
    unreal.load_asset = MagicMock(side_effect=AssertionError("asset dispatch must not start"))
    script = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-cinematics" / "scripts" / "queue_sequence_render.py"

    with patch.dict(sys.modules, {"unreal": unreal}):
        spec = importlib.util.spec_from_file_location("active_mrq_queue", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.queue_sequence_render(
            sequence_path="/Game/Cinematics/LS_Shot",
            output_path=str(tmp_path.resolve()),
        )

    assert result["success"] is False
    assert result["context"]["reason"] == "pie_or_mrq_active"
    assert result["context"]["next_action"]["poll_tool"] == "unreal_cinematics__get_render_status"
    assert result["context"]["next_action"]["retry_tool"] == "unreal_cinematics__queue_sequence_render"
    unreal.load_asset.assert_not_called()


@pytest.mark.parametrize(
    ("relative_script", "function_name", "arguments", "retry_tool"),
    [
        ("unreal-level/scripts/get_level_info.py", "get_level_info", {}, "unreal_level__get_level_info"),
        (
            "unreal-level/scripts/get_world_settings.py",
            "get_world_settings",
            {},
            "unreal_level__get_world_settings",
        ),
        (
            "unreal-level/scripts/set_world_settings.py",
            "set_world_settings",
            {"gravity_z": -980.0},
            "unreal_level__set_world_settings",
        ),
        ("unreal-pcg/scripts/refresh_pcg.py", "refresh_pcg", {}, "unreal_pcg__refresh_pcg"),
    ],
)
def test_editor_world_tools_report_active_pie_with_typed_retry(
    relative_script: str,
    function_name: str,
    arguments: dict,
    retry_tool: str,
) -> None:
    unreal = types.ModuleType("unreal")
    unreal.LevelEditorSubsystem = type("LevelEditorSubsystem", (), {})
    unreal.MoviePipelineQueueSubsystem = type("MoviePipelineQueueSubsystem", (), {})
    unreal.EditorLevelLibrary = types.SimpleNamespace(
        get_editor_world=lambda: None,
        get_all_level_actors=MagicMock(side_effect=AssertionError("world access must not start")),
    )
    pie_subsystem = types.SimpleNamespace(is_in_play_in_editor=lambda: True)
    mrq_subsystem = types.SimpleNamespace(is_rendering=lambda: False)
    unreal.get_editor_subsystem = lambda cls: pie_subsystem if cls is unreal.LevelEditorSubsystem else mrq_subsystem
    script = ROOT / "src" / "dcc_mcp_unreal" / "skills" / relative_script

    with patch.dict(sys.modules, {"unreal": unreal}):
        spec = importlib.util.spec_from_file_location("pie_" + function_name, script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = getattr(module, function_name)(**arguments)

    assert result["success"] is False
    assert result["context"]["reason"] == "pie_or_mrq_active"
    assert result["context"]["pie_active"] is True
    assert result["context"]["mrq_active"] is False
    assert result["context"]["next_action"]["poll_tool"] == "unreal_pie__pie_get_status"
    assert result["context"]["next_action"]["retry_tool"] == retry_tool
    unreal.EditorLevelLibrary.get_all_level_actors.assert_not_called()


def test_preflight_reports_ready_and_multiple_missing_plugins() -> None:
    from dcc_mcp_unreal.plugin_preflight import plugin_preflight

    enabled_unreal = types.SimpleNamespace(
        DccMcpAutomationLibrary=types.SimpleNamespace(
            get_enabled_plugin_names=lambda: [
                "AlembicHairImporter",
                "HairStrands",
                "MovieRenderPipeline",
                "PythonScriptPlugin",
            ]
        )
    )
    ready = plugin_preflight(enabled_unreal, "static_groom_import")
    assert ready["enabled_plugins"] == ["HairStrands", "AlembicHairImporter"]
    assert ready["missing_plugins"] == []
    assert ready["ready"] is True
    assert ready["next_action"] == {"action": "proceed", "capability": "static_groom_import"}

    missing_unreal = types.SimpleNamespace(
        DccMcpAutomationLibrary=types.SimpleNamespace(get_enabled_plugin_names=lambda: [])
    )
    missing = plugin_preflight(missing_unreal, "static_groom_import")
    assert missing["enabled_plugins"] == []
    assert missing["missing_plugins"] == ["HairStrands", "AlembicHairImporter"]


def test_affected_tool_input_schemas_remain_backward_compatible() -> None:
    skills = ROOT / "src" / "dcc_mcp_unreal" / "skills"
    assets = yaml.safe_load((skills / "unreal-assets" / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    cinematics = yaml.safe_load((skills / "unreal-cinematics" / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    automation = yaml.safe_load((skills / "unreal-automation" / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    by_name = {tool["name"]: tool for tool in assets + cinematics + automation}

    assert by_name["import_static_groom"]["input_schema"]["required"] == ["source_path"]
    assert set(by_name["import_asset"]["input_schema"]["properties"]) == {
        "source_path",
        "destination_path",
        "asset_name",
        "replace_existing",
        "combine_meshes",
        "import_materials",
        "import_textures",
        "import_as_skeletal",
        "import_animations",
        "import_as_geometry_cache",
        "source_color_space",
        "non_color_texture",
    }
    assert by_name["queue_sequence_render"]["input_schema"]["required"] == [
        "sequence_path",
        "output_path",
    ]
    for name in ("start_queued_render", "get_render_status", "cancel_queued_render"):
        assert by_name[name]["input_schema"] == {"type": "object", "properties": {}}

    preflight = by_name["preflight_plugins"]
    assert preflight["read_only"] is True
    assert preflight["input_schema"]["properties"]["capability"]["enum"] == [
        "static_groom_import",
        "usd_import",
        "movie_render_queue",
    ]


def test_plugin_discovery_error_fails_closed_with_adapter_update_action() -> None:
    from dcc_mcp_unreal.plugin_preflight import require_plugins

    def unavailable():
        raise OSError("bridge unavailable")

    unreal = types.SimpleNamespace(DccMcpAutomationLibrary=types.SimpleNamespace(get_enabled_plugin_names=unavailable))
    result = require_plugins(unreal, "usd_import")

    assert result is not None
    assert result["success"] is False
    assert result["context"]["ready"] is False
    assert result["context"]["required_plugins"] == ["USDImporter"]
    assert result["context"]["missing_plugins"] == []
    assert result["context"]["next_action"] == {"action": "update_adapter_plugin"}
