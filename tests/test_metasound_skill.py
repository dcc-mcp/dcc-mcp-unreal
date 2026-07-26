"""Behavior tests for the verified MetaSound Builder integration."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from dcc_mcp_unreal import _metasound_builder as api

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILL_ROOT = _REPO_ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-metasound"

NODE_A = "(NodeID=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA)"
NODE_B = "(NodeID=BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB)"
NODE_C = "(NodeID=CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC)"
OUTPUT_A = "(NodeID=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,VertexID=11111111111111111111111111111111)"
OUTPUT_B = "(NodeID=BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB,VertexID=22222222222222222222222222222222)"
INPUT_A = "(NodeID=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,VertexID=33333333333333333333333333333333)"
INPUT_B = "(NodeID=BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB,VertexID=44444444444444444444444444444444)"


class FakeHandle:
    """Unreal-like opaque struct supporting text import/export."""

    default_token = NODE_C

    def __init__(self, token: str = "") -> None:
        self.token = token or self.default_token

    def export_text(self) -> str:
        return self.token

    def import_text(self, token: str) -> None:
        self.token = token


class FakeNodeHandle(FakeHandle):
    default_token = NODE_C


class FakeInputHandle(FakeHandle):
    default_token = INPUT_B


class FakeOutputHandle(FakeHandle):
    default_token = OUTPUT_B


class FakeVersion:
    def export_text(self) -> str:
        return '(Name="UE.Sine.Audio",Number=(Major=1,Minor=0))'


class FakeClassName:
    def __init__(self, namespace: str, name: str, variant: str) -> None:
        self.namespace = namespace
        self.name = name
        self.variant = variant


class FakeLiteral:
    def __init__(self, value: Any) -> None:
        self.value = value


class FakeBuilder:
    """Behavioral fake matching reflected UE 5.8 Builder signatures."""

    def __init__(self) -> None:
        self.nodes: Dict[str, FakeClassName] = {NODE_A: FakeClassName("UE", "Sine", "Audio")}
        self.inputs: Dict[str, List[FakeInputHandle]] = {NODE_A: [FakeInputHandle(INPUT_A)]}
        self.outputs: Dict[str, List[FakeOutputHandle]] = {NODE_A: [FakeOutputHandle(OUTPUT_A)]}
        self.pin_data = {
            INPUT_A: ("Frequency", "Float"),
            INPUT_B: ("Audio", "Audio"),
            OUTPUT_A: ("Audio", "Audio"),
            OUTPUT_B: ("Value", "Float"),
        }
        self.graph_inputs: Dict[str, Dict[str, Any]] = {}
        self.graph_outputs = ["Audio"]
        self.connections = set()
        self.location = None
        self.overwritten = False
        self.fail_add_node = False
        self.fail_remove_node = False

    @property
    def success(self) -> str:
        return "SUCCEEDED"

    def add_node_by_class_name(self, class_name: FakeClassName, major_version: int):
        if self.fail_add_node:
            return FakeNodeHandle(NODE_B), "FAILED"
        node = FakeNodeHandle(NODE_B)
        self.nodes[NODE_B] = class_name
        self.inputs[NODE_B] = [FakeInputHandle(INPUT_B)]
        self.outputs[NODE_B] = [FakeOutputHandle(OUTPUT_B)]
        return node, self.success

    def remove_node(self, node: FakeNodeHandle):
        if self.fail_remove_node:
            return "FAILED"
        self.nodes.pop(node.token, None)
        return self.success

    def contains_node(self, node: FakeNodeHandle) -> bool:
        return node.token in self.nodes

    def find_node_inputs(self, node: FakeNodeHandle):
        return self.inputs[node.token], self.success

    def find_node_outputs(self, node: FakeNodeHandle):
        return self.outputs[node.token], self.success

    def get_node_input_data(self, handle: FakeInputHandle):
        name, data_type = self.pin_data[handle.token]
        return name, data_type, self.success

    def get_node_output_data(self, handle: FakeOutputHandle):
        name, data_type = self.pin_data[handle.token]
        return name, data_type, self.success

    def find_node_class_version(self, node: FakeNodeHandle):
        assert node.token in self.nodes
        return FakeVersion(), self.success

    def get_graph_input_names(self):
        return list(self.graph_inputs), self.success

    def get_graph_output_names(self):
        return self.graph_outputs, self.success

    def add_graph_input_node(
        self,
        name: str,
        data_type: str,
        literal: FakeLiteral,
        is_constructor: bool,
    ):
        assert is_constructor is False
        handle = FakeOutputHandle(OUTPUT_B)
        self.graph_inputs[name] = {
            "type": data_type,
            "literal": literal,
            "handle": handle,
        }
        return handle, self.success

    def remove_graph_input(self, name: str):
        self.graph_inputs.pop(name, None)
        return self.success

    def find_graph_input_node(self, name: str):
        value = self.graph_inputs[name]
        return FakeNodeHandle(NODE_C), value["type"], value["handle"], self.success

    def set_graph_input_default(self, name: str, literal: FakeLiteral):
        self.graph_inputs[name]["literal"] = literal
        return self.success

    def get_graph_input_default(self, name: str):
        return self.graph_inputs[name]["literal"], self.success

    def contains_node_output(self, handle: FakeOutputHandle) -> bool:
        return handle.token in self.pin_data

    def contains_node_input(self, handle: FakeInputHandle) -> bool:
        return handle.token in self.pin_data

    def nodes_are_connected(self, output: FakeOutputHandle, input_: FakeInputHandle) -> bool:
        return (output.token, input_.token) in self.connections

    def connect_nodes(self, output: FakeOutputHandle, input_: FakeInputHandle):
        self.connections.add((output.token, input_.token))
        return self.success

    def disconnect_nodes(self, output: FakeOutputHandle, input_: FakeInputHandle):
        self.connections.discard((output.token, input_.token))
        return self.success

    def build_and_overwrite_meta_sound(self, asset: Any, force_unique: bool) -> None:
        assert force_unique is False
        self.overwritten = True


class FakeMetaSoundSource:
    def __init__(self, builder: FakeBuilder) -> None:
        self.builder = builder


class FakeEditorAssetLibrary:
    def __init__(self) -> None:
        self.assets: Dict[str, FakeMetaSoundSource] = {}
        self.saved: List[str] = []
        self.save_result = True

    def does_asset_exist(self, path: str) -> bool:
        return path in self.assets

    def load_asset(self, path: str):
        return self.assets.get(path)

    def delete_asset(self, path: str) -> bool:
        return self.assets.pop(path, None) is not None

    def save_asset(self, path: str, only_if_is_dirty: bool = True) -> bool:
        assert only_if_is_dirty is False
        self.saved.append(path)
        return self.save_result


class FakeBuilderSubsystem:
    def __init__(self) -> None:
        self.builder = FakeBuilder()
        self.unregistered: List[str] = []
        self.unregister_result = True

    def create_source_builder(self, name: str, output_format: str, is_one_shot: bool):
        assert name.startswith("DccMcp_")
        assert output_format in {"MONO", "STEREO", "QUAD", "FIVE_DOT_ONE", "SEVEN_DOT_ONE"}
        assert isinstance(is_one_shot, bool)
        return (
            self.builder,
            FakeOutputHandle(OUTPUT_A),
            FakeInputHandle(INPUT_A),
            [FakeInputHandle(INPUT_B)],
            "SUCCEEDED",
        )

    def unregister_source_builder(self, name: str) -> bool:
        self.unregistered.append(name)
        return self.unregister_result

    @staticmethod
    def create_bool_meta_sound_literal(value: bool):
        return FakeLiteral(value), "Bool"

    @staticmethod
    def create_float_meta_sound_literal(value: float):
        return FakeLiteral(value), "Float"

    @staticmethod
    def create_int_meta_sound_literal(value: int):
        return FakeLiteral(value), "Int32"

    @staticmethod
    def create_string_meta_sound_literal(value: str):
        return FakeLiteral(value), "String"


class FakeEditorSubsystem:
    def __init__(self, asset_library: FakeEditorAssetLibrary) -> None:
        self.asset_library = asset_library

    @staticmethod
    def find_or_begin_building(asset: FakeMetaSoundSource):
        return asset.builder, "SUCCEEDED"

    def build_to_asset(
        self,
        builder: FakeBuilder,
        author: str,
        asset_name: str,
        package_path: str,
    ):
        assert author
        asset = FakeMetaSoundSource(builder)
        self.asset_library.assets[f"{package_path}/{asset_name}"] = asset
        return asset, "SUCCEEDED"

    @staticmethod
    def set_node_location(builder: FakeBuilder, node: FakeNodeHandle, position: Any):
        builder.location = (node.token, position.x, position.y)
        return "SUCCEEDED"


class FakeValidationResult:
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return f"DataValidationResult.{self.name}"


class FakeValidatorSubsystem:
    def __init__(self, validation_results: Any) -> None:
        self.validation_results = validation_results
        self.result = validation_results.VALID
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def is_object_valid(self, asset: Any, usecase: str):
        assert isinstance(asset, FakeMetaSoundSource)
        assert usecase == "SCRIPT"
        return self.result, self.errors, self.warnings


@pytest.fixture
def fake_unreal(monkeypatch: pytest.MonkeyPatch):
    asset_library = FakeEditorAssetLibrary()
    builder_subsystem = FakeBuilderSubsystem()
    editor_subsystem = FakeEditorSubsystem(asset_library)
    validation_results = SimpleNamespace(
        VALID=FakeValidationResult("VALID"),
        INVALID=FakeValidationResult("INVALID"),
        NOT_VALIDATED=FakeValidationResult("NOT_VALIDATED"),
    )
    validator_subsystem = FakeValidatorSubsystem(validation_results)

    class SystemLibrary:
        version = "5.8.0-55116800+++UE5+Release-5.8"

        @classmethod
        def get_engine_version(cls) -> str:
            return cls.version

    class Vector2D:
        def __init__(self, x: float, y: float) -> None:
            self.x = x
            self.y = y

    unreal = SimpleNamespace(
        SystemLibrary=SystemLibrary,
        MetaSoundBuilderResult=SimpleNamespace(SUCCEEDED="SUCCEEDED"),
        MetaSoundBuilderSubsystem=type("MetaSoundBuilderSubsystem", (), {}),
        MetaSoundEditorSubsystem=type("MetaSoundEditorSubsystem", (), {}),
        EditorValidatorSubsystem=type("EditorValidatorSubsystem", (), {}),
        MetaSoundSource=FakeMetaSoundSource,
        MetaSoundOutputAudioFormat=SimpleNamespace(
            MONO="MONO",
            STEREO="STEREO",
            QUAD="QUAD",
            FIVE_DOT_ONE="FIVE_DOT_ONE",
            SEVEN_DOT_ONE="SEVEN_DOT_ONE",
        ),
        MetaSoundNodeHandle=FakeNodeHandle,
        MetaSoundBuilderNodeInputHandle=FakeInputHandle,
        MetaSoundBuilderNodeOutputHandle=FakeOutputHandle,
        MetasoundFrontendClassName=FakeClassName,
        DataValidationUsecase=SimpleNamespace(SCRIPT="SCRIPT"),
        DataValidationResult=validation_results,
        Vector2D=Vector2D,
        EditorAssetLibrary=asset_library,
    )

    def get_engine_subsystem(subsystem_type: Any):
        assert subsystem_type is unreal.MetaSoundBuilderSubsystem
        return builder_subsystem

    def get_editor_subsystem(subsystem_type: Any):
        if subsystem_type is unreal.MetaSoundEditorSubsystem:
            return editor_subsystem
        if subsystem_type is unreal.EditorValidatorSubsystem:
            return validator_subsystem
        raise AssertionError(f"unexpected subsystem {subsystem_type}")

    unreal.get_engine_subsystem = get_engine_subsystem
    unreal.get_editor_subsystem = get_editor_subsystem
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    return SimpleNamespace(
        unreal=unreal,
        assets=asset_library,
        builders=builder_subsystem,
        editor=editor_subsystem,
        validator=validator_subsystem,
    )


def add_existing_asset(fake_unreal: Any, path: str = "/Game/Audio/MS_Test") -> FakeMetaSoundSource:
    asset = FakeMetaSoundSource(fake_unreal.builders.builder)
    fake_unreal.assets.assets[path] = asset
    return asset


@pytest.mark.parametrize(
    "path",
    ["", "/Engine/Test", "C:/Test", "/Game/Has Space", "/Game/Test.Asset", "/Game/../Test"],
)
def test_asset_path_rejects_non_package_paths(path: str) -> None:
    with pytest.raises(api.MetaSoundOperationError):
        api.validate_asset_path(path)


def test_unknown_engine_version_fails_closed(fake_unreal: Any) -> None:
    fake_unreal.unreal.SystemLibrary.version = "unknown"
    with pytest.raises(api.MetaSoundOperationError, match="parse"):
        api.create_source("/Game/Audio/MS_Test", "dcc-mcp", "Mono", True)


def test_create_source_uses_builder_api_and_returns_handles(fake_unreal: Any) -> None:
    result = api.create_source("/Game/Audio/MS_Test", "Tester", "Mono", True)
    assert result["asset_path"] == "/Game/Audio/MS_Test"
    assert result["on_play_output_handle"] == OUTPUT_A
    assert result["on_finished_input_handle"] == INPUT_A
    assert result["audio_output_input_handles"] == [INPUT_B]
    assert fake_unreal.assets.saved == ["/Game/Audio/MS_Test"]
    assert len(fake_unreal.builders.unregistered) == 1


def test_create_source_rejects_existing_asset(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    with pytest.raises(api.MetaSoundOperationError, match="already exists"):
        api.create_source("/Game/Audio/MS_Test", "Tester", "Mono", True)


def test_create_source_accepts_absent_legacy_builder_registration(fake_unreal: Any) -> None:
    fake_unreal.builders.unregister_result = False
    result = api.create_source("/Game/Audio/MS_Test", "Tester", "Mono", True)
    assert result["asset_path"] == "/Game/Audio/MS_Test"
    assert len(fake_unreal.builders.unregistered) == 1


def test_create_source_rolls_back_an_unconfirmed_save(fake_unreal: Any) -> None:
    fake_unreal.assets.save_result = False
    with pytest.raises(api.MetaSoundOperationError, match="did not confirm"):
        api.create_source("/Game/Audio/MS_Test", "Tester", "Mono", True)
    assert "/Game/Audio/MS_Test" not in fake_unreal.assets.assets


def test_add_input_uses_typed_literal_factory(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    result = api.add_graph_input("/Game/Audio/MS_Test", "Gain", "Float", 0.25)
    graph_input = fake_unreal.builders.builder.graph_inputs["Gain"]
    assert graph_input["literal"].value == 0.25
    assert graph_input["type"] == "Float"
    assert result["output_handle"] == OUTPUT_B


def test_add_input_rejects_unsupported_or_wrong_literal(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    with pytest.raises(api.MetaSoundOperationError, match="one of"):
        api.add_graph_input("/Game/Audio/MS_Test", "Wave", "WaveTable", "/Game/Wave")
    with pytest.raises(api.MetaSoundOperationError, match="finite number"):
        api.add_graph_input("/Game/Audio/MS_Test", "Gain", "Float", "loud")


def test_add_node_uses_exact_class_and_reflects_pins(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    result = api.add_node(
        "/Game/Audio/MS_Test",
        "UE",
        "Sine",
        "Audio",
        1,
        40.0,
        -10.0,
    )
    registered = fake_unreal.builders.builder.nodes[NODE_B]
    assert (registered.namespace, registered.name, registered.variant) == ("UE", "Sine", "Audio")
    assert result["node_handle"] == NODE_B
    assert result["inputs"] == [{"name": "Audio", "data_type": "Audio", "handle": INPUT_B}]
    assert result["outputs"] == [{"name": "Value", "data_type": "Float", "handle": OUTPUT_B}]
    assert fake_unreal.builders.builder.location == (NODE_B, 40.0, -10.0)


def test_failed_builder_result_is_not_reported_as_success(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    fake_unreal.builders.builder.fail_add_node = True
    with pytest.raises(api.MetaSoundOperationError, match="FAILED"):
        api.add_node("/Game/Audio/MS_Test", "UE", "Sine", "Audio", 1, 0, 0)


@pytest.mark.parametrize("position", [float("nan"), float("inf"), True])
def test_add_node_rejects_non_finite_positions(fake_unreal: Any, position: Any) -> None:
    add_existing_asset(fake_unreal)
    with pytest.raises(api.MetaSoundOperationError, match="finite number"):
        api.add_node("/Game/Audio/MS_Test", "UE", "Sine", "Audio", 1, position, 0)


def test_connect_validates_handles_and_is_idempotent(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    first = api.connect_handles("/Game/Audio/MS_Test", OUTPUT_A, INPUT_A)
    second = api.connect_handles("/Game/Audio/MS_Test", OUTPUT_A, INPUT_A)
    assert first["changed"] is True
    assert second["changed"] is False
    with pytest.raises(api.MetaSoundOperationError, match="Invalid"):
        api.connect_handles("/Game/Audio/MS_Test", "made-up", INPUT_A)


def test_set_default_derives_declared_type(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    api.add_graph_input("/Game/Audio/MS_Test", "Gain", "Float", 0.25)
    result = api.set_graph_input_default("/Game/Audio/MS_Test", "Gain", 0.75)
    assert result["data_type"] == "Float"
    assert fake_unreal.builders.builder.graph_inputs["Gain"]["literal"].value == 0.75


def test_set_default_rolls_back_when_save_is_unconfirmed(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    api.add_graph_input("/Game/Audio/MS_Test", "Gain", "Float", 0.25)
    fake_unreal.assets.save_result = False
    with pytest.raises(api.MetaSoundOperationError, match="did not confirm"):
        api.set_graph_input_default("/Game/Audio/MS_Test", "Gain", 0.75)
    assert fake_unreal.builders.builder.graph_inputs["Gain"]["literal"].value == 0.25


def test_inspect_node_round_trips_opaque_handle(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    result = api.inspect_node("/Game/Audio/MS_Test", NODE_A)
    assert result["node_handle"] == NODE_A
    assert "Major=1" in result["class_version"]
    assert result["outputs"][0]["handle"] == OUTPUT_A


def test_validation_is_conclusive_or_fails_closed(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    valid = api.validate_graph("/Game/Audio/MS_Test")
    assert valid["valid"] is True
    assert valid["graph_outputs"] == ["Audio"]

    fake_unreal.validator.result = fake_unreal.unreal.DataValidationResult.INVALID
    fake_unreal.validator.errors = ["cycle detected"]
    invalid = api.validate_graph("/Game/Audio/MS_Test")
    assert invalid["valid"] is False
    assert invalid["errors"] == ["cycle detected"]

    fake_unreal.validator.result = fake_unreal.unreal.DataValidationResult.NOT_VALIDATED
    with pytest.raises(api.MetaSoundOperationError, match="inconclusive"):
        api.validate_graph("/Game/Audio/MS_Test")


def test_build_overwrites_validates_and_saves(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    result = api.build_graph("/Game/Audio/MS_Test")
    assert fake_unreal.builders.builder.overwritten is True
    assert result["valid"] is True
    assert fake_unreal.assets.saved == ["/Game/Audio/MS_Test"]


def test_unconfirmed_save_is_an_error(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    fake_unreal.assets.save_result = False
    with pytest.raises(api.MetaSoundOperationError, match="did not confirm"):
        api.add_node("/Game/Audio/MS_Test", "UE", "Sine", "Audio", 1, 0, 0)
    assert NODE_B not in fake_unreal.builders.builder.nodes


def test_failed_rollback_reports_possible_partial_change(fake_unreal: Any) -> None:
    add_existing_asset(fake_unreal)
    fake_unreal.assets.save_result = False
    fake_unreal.builders.builder.fail_remove_node = True
    with pytest.raises(api.MetaSoundOperationError, match="partial change"):
        api.add_node("/Game/Audio/MS_Test", "UE", "Sine", "Audio", 1, 0, 0)


def test_scripts_lazy_import_unreal_and_avoid_invented_api() -> None:
    scripts_dir = _SKILL_ROOT / "scripts"
    forbidden = (
        "MetaSoundOutputNode",
        "MetaSoundParameterType",
        ".get_editor_subsystem(",
        ".has_cycle(",
        ".get_nodes(",
    )
    for script_path in scripts_dir.glob("*.py"):
        source = script_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(script_path))
        for node in tree.body:
            if isinstance(node, ast.Import):
                assert all(alias.name != "unreal" for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module != "unreal" and not node.module.startswith("unreal.")
        assert not any(value in source for value in forbidden)


def test_tool_manifest_matches_implemented_contract() -> None:
    root = _SKILL_ROOT
    manifest = (root / "tools.yaml").read_text(encoding="utf-8")
    tool_names = set(re.findall(r"^  - name: (\S+)$", manifest, re.MULTILINE))
    assert tool_names == {
        "create_metasound_source",
        "add_metasound_input",
        "add_metasound_node",
        "connect_metasound_nodes",
        "set_metasound_parameter_default",
        "build_metasound",
        "inspect_metasound_node",
        "validate_metasound_graph",
    }
    assert "node_type:" not in manifest
    connect_section = manifest.split("  - name: connect_metasound_nodes", 1)[1].split("  - name:", 1)[0]
    assert "idempotent: true" in connect_section
    for source_file in re.findall(r"^    source_file: (\S+)$", manifest, re.MULTILINE):
        assert (root / source_file).is_file()
