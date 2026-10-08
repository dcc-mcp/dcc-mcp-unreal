"""Contract tests for collision measurements through Unreal's public Python binding."""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "src/dcc_mcp_unreal/skills/unreal-level"
START = {"x": 0, "y": 0, "z": 200}
END = {"x": 0, "y": 0, "z": -200}
PATH = "/Game/Test/UEDPIE_0_Fixture.Fixture"


class NativeObject:
    def __init__(self, name, path, class_path):
        self.name = name
        self.path = path
        self.class_path = class_path

    def get_name(self):
        return self.name

    def get_path_name(self):
        return self.path

    def get_class(self):
        return SimpleNamespace(get_path_name=lambda: self.class_path)


class NativeHit:
    def __init__(self, values):
        self.values = list(values)
        self.to_tuple = MagicMock(side_effect=lambda: tuple(self.values))

    def to_tuple(self):
        return tuple(self.values)


def vector(**value):
    return SimpleNamespace(**value)


@pytest.fixture
def harness(monkeypatch):
    spec = importlib.util.spec_from_file_location("spatial_line_trace", SKILL / "scripts/line_trace.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    selected = NativeObject("Fixture", PATH, "/Script/Engine.World")
    pie_getter = MagicMock(return_value=selected)
    editor_getter = MagicMock(return_value=selected)
    subsystem = SimpleNamespace(get_game_world=pie_getter, get_editor_world=editor_getter)
    subsystem_getter = MagicMock(return_value=subsystem)
    floor = NativeObject("Floor", PATH + ":PersistentLevel.Floor", "/Script/Engine.Actor")
    component = NativeObject("Collision", floor.path + ".Collision", "/Script/Engine.BoxComponent")
    second = NativeObject("Other", PATH + ":PersistentLevel.Other", "/Script/Engine.Actor")
    hit = NativeHit(
        [
            True,
            False,
            0.5,
            200.0,
            vector(x=0, y=0, z=0),
            vector(x=0, y=0, z=0),
            vector(x=0, y=0, z=1),
            vector(x=0, y=0, z=1),
            None,
            floor,
            component,
            "hit_bone",
            "bone",
            0,
            0,
            -1,
            vector(**START),
            vector(**END),
        ]
    )
    trace = MagicMock(return_value=hit)
    actor_getter = MagicMock(return_value=[floor, second])
    channel_cast = MagicMock(side_effect=lambda index: SimpleNamespace(value=index))
    debug_none = object()
    unreal = SimpleNamespace(
        SystemLibrary=SimpleNamespace(line_trace_single=trace),
        HitResult=NativeHit,
        Vector=vector,
        TraceTypeQuery=SimpleNamespace(cast=channel_cast),
        DrawDebugTrace=SimpleNamespace(NONE=debug_none),
        GameplayStatics=SimpleNamespace(get_all_actors_of_class=actor_getter),
        Actor=object(),
        UnrealEditorSubsystem=object(),
        get_editor_subsystem=subsystem_getter,
        EditorLevelLibrary=SimpleNamespace(get_game_world=MagicMock(), get_editor_world=MagicMock()),
    )
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    return SimpleNamespace(
        module=module,
        hit=hit,
        trace=trace,
        pie_getter=pie_getter,
        editor_getter=editor_getter,
        subsystem=subsystem,
        subsystem_getter=subsystem_getter,
        selected=selected,
        unreal=unreal,
        floor=floor,
        component=component,
        second=second,
        actor_getter=actor_getter,
        channel_cast=channel_cast,
        debug_none=debug_none,
    )


def call(h, **kwargs):
    return h.module.line_trace(**{"start": START, "end": END, "world": "pie", **kwargs})


def assert_error(result, reason):
    assert result["success"] is False
    assert result["context"]["reason"] == reason
    assert result["context"].get("status") != "no_hit"


def test_public_native_hit_returns_measurements_and_exact_identity(harness):
    h = harness
    result = call(h, expected_world_path=PATH)
    assert result["success"] is True
    context = result["context"]
    assert context["status"] == "hit" and context["blocking_hit"] is True
    assert context["start_penetrating"] is False
    assert context["distance_cm"] == 200 and context["time"] == 0.5
    assert context["location"] == context["impact_point"] == {"x": 0, "y": 0, "z": 0}
    assert context["normal"] == context["impact_normal"] == {"x": 0, "y": 0, "z": 1}
    assert context["trace_length_cm"] == 400
    assert context["unit"] == "cm" and context["coordinate_space"] == "world"
    assert context["start"] == START and context["end"] == END
    assert context["world"] == {"name": "Fixture", "path": PATH, "type": "pie"}
    assert context["actor"] == {"name": "Floor", "path": h.floor.path, "class": "/Script/Engine.Actor"}
    assert context["component"] == {
        "name": "Collision",
        "path": h.component.path,
        "class": "/Script/Engine.BoxComponent",
    }
    args = h.trace.call_args.args
    assert args[0] is h.selected
    assert vars(args[1]) == START and vars(args[2]) == END
    assert args[3].value == 0
    assert args[4:] == (False, [], h.debug_none, False)
    h.channel_cast.assert_called_once_with(0)
    h.hit.to_tuple.assert_called_once_with()
    h.pie_getter.assert_called_once_with()
    h.editor_getter.assert_not_called()
    h.actor_getter.assert_not_called()
    jsonschema.validate(result, tool()["output_schema"])


def test_camera_complex_trace_and_editor_world_are_explicit(harness):
    h = harness
    result = call(h, collision_channel="camera", trace_complex=True, world="editor")
    assert result["success"] is True
    assert result["context"]["collision_channel"] == "camera"
    assert result["context"]["trace_complex"] is True
    assert result["context"]["world"]["type"] == "editor"
    h.channel_cast.assert_called_once_with(1)
    assert h.trace.call_args.args[3].value == 1
    assert h.trace.call_args.args[4] is True
    h.editor_getter.assert_called_once_with()
    h.pie_getter.assert_not_called()


def test_none_is_a_successful_miss_with_null_hit_fields(harness):
    h = harness
    h.trace.return_value = None
    result = call(h)
    assert result["success"] is True
    context = result["context"]
    assert context["status"] == "no_hit"
    assert context["blocking_hit"] is context["start_penetrating"] is False
    assert all(field in context and context[field] is None for field in h.module.HIT_FIELDS)
    assert context["trace_length_cm"] == 400 and context["start"] == START and context["end"] == END
    h.hit.to_tuple.assert_not_called()
    jsonschema.validate(result, tool()["output_schema"])


def test_float32_native_endpoints_are_used_for_valid_decimal_coordinates(harness):
    h = harness
    requested_start = {"x": 0.1, "y": 0.1, "z": 200}
    requested_end = {"x": 0.1, "y": 0.1, "z": -200}

    def float32_vector(**value):
        return vector(**{axis: struct.unpack("f", struct.pack("f", item))[0] for axis, item in value.items()})

    def native_trace(*args):
        native_start, native_end = args[1:3]
        native_impact = vector(x=native_start.x, y=native_start.y, z=0.0)
        h.hit.values[4:6] = [native_impact, native_impact]
        h.hit.values[-2:] = [native_start, native_end]
        return h.hit

    h.unreal.Vector = MagicMock(side_effect=float32_vector)
    h.trace.side_effect = native_trace
    result = call(h, start=requested_start, end=requested_end)
    assert result["success"] is True
    native_start, native_end = h.trace.call_args.args[1:3]
    assert native_start.x != requested_start["x"]
    assert result["context"]["start"] == vars(native_start)
    assert result["context"]["end"] == vars(native_end)
    assert (
        result["context"]["location"]
        == result["context"]["impact_point"]
        == {"x": native_start.x, "y": native_start.y, "z": 0.0}
    )
    assert result["context"]["trace_length_cm"] == 400.0
    assert h.unreal.Vector.call_count == 2


def test_segment_quantized_to_zero_by_float32_is_rejected_before_trace(harness):
    h = harness
    requested_start = {"x": 9_000_000.0, "y": 0.0, "z": 200.0}
    requested_end = {**requested_start, "x": requested_start["x"] + 0.01}

    def float32_vector(**value):
        return vector(**{axis: struct.unpack("f", struct.pack("f", item))[0] for axis, item in value.items()})

    assert requested_end["x"] > requested_start["x"]
    assert vars(float32_vector(**requested_start)) == vars(float32_vector(**requested_end))
    h.unreal.Vector = MagicMock(side_effect=float32_vector)
    assert_error(call(h, start=requested_start, end=requested_end), "invalid_parameters")
    h.trace.assert_not_called()
    h.hit.to_tuple.assert_not_called()
    assert h.unreal.Vector.call_count == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start": {"x": True, "y": 0, "z": 0}},
        {"start": {"x": "0", "y": 0, "z": 0}},
        {"start": {"x": float("nan"), "y": 0, "z": 0}},
        {"start": {"x": float("inf"), "y": 0, "z": 0}},
        {"start": {"x": 10000001, "y": 0, "z": 0}},
        {"start": {"x": 0, "y": 0}},
        {"start": {"x": 0, "y": 0, "z": 0, "w": 1}},
        {"start": [0, 0, 0]},
        {"end": None},
        {"end": START},
        {"start": {"x": -10000000, "y": 0, "z": 0}, "end": {"x": 10000000, "y": 0, "z": 0}},
        {"world": "auto"},
        {"collision_channel": "unknown"},
        {"collision_channel": "Visibility"},
        {"trace_complex": "false"},
        {"trace_complex": 1},
        {"expected_world_path": None},
        {"ignored_actor_paths": ["same", "same"]},
        {"ignored_actor_paths": [" "]},
        {"ignored_actor_paths": [None]},
        {"ignored_actor_paths": "Floor"},
        {"ignored_actor_paths": [str(i) for i in range(65)]},
    ],
)
def test_invalid_parameters_never_reach_unreal(harness, kwargs):
    h = harness
    assert_error(call(h, **kwargs), "invalid_parameters")
    h.trace.assert_not_called()
    h.subsystem_getter.assert_not_called()
    h.actor_getter.assert_not_called()


def test_world_guard_and_unavailable_pie_do_not_fall_back(harness):
    h = harness
    result = call(h, expected_world_path="/Game/Other.Other")
    assert_error(result, "world_mismatch")
    assert result["context"]["actual_world_path"] == PATH
    h.pie_getter.return_value = None
    assert_error(call(h), "world_unavailable")
    h.unreal.EditorLevelLibrary.get_game_world.assert_not_called()
    h.editor_getter.assert_not_called()
    h.trace.assert_not_called()


def test_none_subsystem_is_an_explicit_error_without_legacy_fallback(harness):
    h = harness
    h.subsystem_getter.return_value = None
    assert_error(call(h), "native_call_failed")
    h.unreal.EditorLevelLibrary.get_game_world.assert_not_called()
    h.pie_getter.assert_not_called()
    h.trace.assert_not_called()


@pytest.mark.parametrize("mode, getter_name", [("pie", "get_game_world"), ("editor", "get_editor_world")])
def test_missing_modern_world_api_uses_only_the_requested_legacy_world(harness, mode, getter_name):
    h = harness
    h.unreal.UnrealEditorSubsystem = None
    getter = getattr(h.unreal.EditorLevelLibrary, getter_name)
    getter.return_value = h.selected
    assert call(h, world=mode)["success"] is True
    getter.assert_called_once_with()
    h.subsystem_getter.assert_not_called()


@pytest.mark.parametrize("stage", ["subsystem", "world"])
def test_world_api_exceptions_do_not_fall_back(harness, stage):
    h = harness
    failing = h.subsystem_getter if stage == "subsystem" else h.pie_getter
    failing.side_effect = RuntimeError("world lookup failed")
    result = call(h)
    assert_error(result, "native_call_failed")
    assert "world lookup failed" in str(result)
    h.unreal.EditorLevelLibrary.get_game_world.assert_not_called()
    h.trace.assert_not_called()


@pytest.mark.parametrize("api", ["trace", "reader"])
def test_missing_public_bindings_are_not_no_hit_even_for_a_miss(harness, api):
    h = harness
    h.trace.return_value = None
    if api == "trace":
        h.unreal.SystemLibrary.line_trace_single = None
    else:
        h.unreal.HitResult = SimpleNamespace(to_tuple=None)
    assert_error(call(h), "native_bridge_unavailable")
    h.trace.assert_not_called()
    h.subsystem_getter.assert_not_called()


@pytest.mark.parametrize("stage", ["trace", "reader", "identity", "actor_lookup", "channel_cast"])
def test_native_exceptions_fail_explicitly_without_becoming_no_hit(harness, stage):
    h = harness
    kwargs = {}
    if stage == "trace":
        failing = h.trace
    elif stage == "reader":
        failing = h.hit.to_tuple
    elif stage == "identity":
        h.floor.get_name = MagicMock()
        failing = h.floor.get_name
    elif stage == "actor_lookup":
        kwargs["ignored_actor_paths"] = [h.floor.path]
        failing = h.actor_getter
    else:
        failing = h.channel_cast
    failing.side_effect = RuntimeError("native API interrupted")
    result = call(h, **kwargs)
    assert_error(result, "native_call_failed")
    assert "native API interrupted" in str(result)


def test_a_hit_without_an_instance_reader_does_not_become_no_hit(harness):
    h = harness
    h.trace.return_value = SimpleNamespace()
    assert_error(call(h), "native_call_failed")


def test_cast_must_resolve_the_requested_builtin_channel(harness):
    h = harness
    h.channel_cast.side_effect = None
    h.channel_cast.return_value = SimpleNamespace(value=7)
    assert_error(call(h), "native_call_failed")
    h.trace.assert_not_called()


def test_ignored_actor_paths_resolve_to_exact_actors_in_selected_world(harness):
    h = harness
    paths = [h.second.path, h.floor.path]
    result = call(h, ignored_actor_paths=paths)
    assert result["success"] is True
    h.actor_getter.assert_called_once_with(h.selected, h.unreal.Actor)
    assert h.trace.call_args.args[5] == [h.second, h.floor]
    assert result["context"]["ignored_actor_paths"] == paths


@pytest.mark.parametrize("path", ["/Game/Other.Other:PersistentLevel.Floor", PATH + ":PersistentLevel.Missing"])
def test_unknown_or_other_world_ignored_actor_paths_fail_before_trace(harness, path):
    h = harness
    assert_error(call(h, ignored_actor_paths=[path]), "ignored_actor_not_found")
    h.actor_getter.assert_called_once_with(h.selected, h.unreal.Actor)
    h.trace.assert_not_called()


@pytest.mark.parametrize(
    "index, value, reason",
    [
        (2, True, "native_call_failed"),
        (2, "0.5", "native_call_failed"),
        (2, float("nan"), "native_call_failed"),
        (2, -0.1, "native_call_failed"),
        (2, 1.1, "native_call_failed"),
        (3, -1, "native_call_failed"),
        (3, 401, "native_invalid_result"),
        (3, True, "native_call_failed"),
        (3, float("nan"), "native_call_failed"),
        (3, 199, "native_invalid_result"),
        (2, 0.4, "native_invalid_result"),
        (4, vector(x=0, y=0, z=1), "native_invalid_result"),
        (5, vector(x=0, y=0, z=-1), "native_invalid_result"),
        (6, vector(x=0, y=0, z=2), "native_invalid_result"),
        (7, vector(x=0, y=0, z=0), "native_invalid_result"),
        (16, vector(**END), "native_invalid_result"),
        (17, vector(**START), "native_invalid_result"),
    ],
)
def test_inconsistent_native_measurements_are_rejected(harness, index, value, reason):
    h = harness
    h.hit.values[index] = value
    assert_error(call(h), reason)


@pytest.mark.parametrize("field, value", [("name", ""), ("path", None), ("class_path", False)])
def test_incomplete_native_identity_is_rejected(harness, field, value):
    h = harness
    setattr(h.floor, field, value)
    result = call(h)
    assert result["success"] is False
    assert result["context"].get("status") != "no_hit"


@pytest.mark.parametrize("index, value", [(0, False), (0, 1), (1, 0), (4, None), (6, vector(x=0, y=0, z=float("inf")))])
def test_decoder_errors_fail_explicitly_in_the_tool(harness, index, value):
    h = harness
    h.hit.values[index] = value
    assert_error(call(h), "native_call_failed")


def test_initial_penetration_keeps_native_zero_measurements_and_zero_normals(harness):
    h = harness
    h.hit.values[1:4] = [True, 0.0, 0.0]
    h.hit.values[4] = vector(**START)
    h.hit.values[5] = vector(**START)
    h.hit.values[6] = vector(x=0, y=0, z=0)
    h.hit.values[7] = vector(x=0, y=0, z=0)
    result = call(h)
    assert result["success"] is True
    assert result["context"]["start_penetrating"] is True
    assert result["context"]["distance_cm"] == result["context"]["time"] == 0.0
    assert result["context"]["location"] == result["context"]["impact_point"] == START
    assert result["context"]["normal"] == result["context"]["impact_normal"] == {"x": 0, "y": 0, "z": 0}


@pytest.mark.parametrize(
    "index, value",
    [
        (2, 0.25),
        (2, 1e-12),
        (3, 1.0),
        (3, 1e-12),
        *[(index, vector(**{**START, axis: START[axis] + 1.0})) for index in (4, 5) for axis in "xyz"],
    ],
)
def test_initial_penetration_rejects_nonzero_measurements_or_disagreeing_points(harness, index, value):
    h = harness
    h.hit.values[1:4] = [True, 0.0, 0.0]
    h.hit.values[4] = vector(**START)
    h.hit.values[5] = vector(**START)
    h.hit.values[6] = vector(x=0, y=0, z=0)
    h.hit.values[7] = vector(x=0, y=0, z=0)
    h.hit.values[index] = value
    assert_error(call(h), "native_invalid_result")


def test_initial_penetration_allows_point_rounding_within_spatial_tolerance(harness):
    h = harness
    h.hit.values[1:4] = [True, 0.0, 0.0]
    h.hit.values[4] = vector(**START)
    h.hit.values[5] = vector(**{**START, "x": 0.005})
    h.hit.values[6] = vector(x=0, y=0, z=0)
    h.hit.values[7] = vector(x=0, y=0, z=0)
    result = call(h)
    assert result["success"] is True
    assert result["context"]["impact_point"]["x"] == 0.005


def tool():
    return next(
        entry
        for entry in yaml.safe_load((SKILL / "tools.yaml").read_text(encoding="utf-8"))["tools"]
        if entry["name"] == "line_trace"
    )


def test_public_contract_is_read_only_and_main_thread():
    contract = tool()
    assert contract["read_only"] is True and contract["destructive"] is False
    assert contract["affinity"] == "main" and contract["enforce_thread_affinity"] is True
    assert set(contract["input_schema"]["required"]) == {"world", "start", "end"}
    assert set(contract["input_schema"]["properties"]["collision_channel"]["enum"]) == {"visibility", "camera"}
    for example in contract["call_examples"]:
        jsonschema.validate(example["arguments"], contract["input_schema"])


def test_output_contract_requires_measurements_and_explicit_miss(harness):
    schema = tool()["output_schema"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"success": True, "message": "incomplete", "context": {}}, schema)
    result = call(harness)
    result["context"]["status"] = "no_hit"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, schema)
