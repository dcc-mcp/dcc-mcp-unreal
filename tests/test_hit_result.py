"""Unit tests for the public native BreakHitResult tuple decoder."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dcc_mcp_unreal.hit_result import read_hit_result


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


def vector(x=0.0, y=0.0, z=0.0):
    return SimpleNamespace(x=x, y=y, z=z)


def native_values(layout=18):
    actor = NativeObject("Floor", "/Game/Fixture.Fixture:PersistentLevel.Floor", "/Script/Engine.Actor")
    component = NativeObject("Box", actor.path + ".Box", "/Script/Engine.BoxComponent")
    prefix = [
        True,
        False,
        0.5,
        200.0,
        vector(),
        vector(),
        vector(z=1),
        vector(z=1),
        object(),
        actor,
        component,
    ]
    middle = ["hit_bone", "bone", 71, 19, -1][: layout - 13]
    return prefix + middle + [vector(z=200), vector(z=-200)]


def hit_with(values):
    return SimpleNamespace(
        to_tuple=MagicMock(return_value=tuple(values)),
        export_text=MagicMock(side_effect=AssertionError("Text export must never decode collision")),
        get_editor_property=MagicMock(side_effect=AssertionError("Reflected properties must never decode collision")),
    )


@pytest.mark.parametrize("layout", [16, 17, 18])
def test_supported_public_tuple_layouts_use_common_prefix_and_tail(layout):
    values = native_values(layout)
    assert len(values) == layout
    hit = hit_with(values)
    result = read_hit_result(hit)
    assert result == {
        "status": "hit",
        "blocking_hit": True,
        "start_penetrating": False,
        "distance_cm": 200.0,
        "time": 0.5,
        "location": {"x": 0.0, "y": 0.0, "z": 0.0},
        "impact_point": {"x": 0.0, "y": 0.0, "z": 0.0},
        "normal": {"x": 0.0, "y": 0.0, "z": 1},
        "impact_normal": {"x": 0.0, "y": 0.0, "z": 1},
        "actor": {
            "name": "Floor",
            "path": "/Game/Fixture.Fixture:PersistentLevel.Floor",
            "class": "/Script/Engine.Actor",
        },
        "component": {
            "name": "Box",
            "path": "/Game/Fixture.Fixture:PersistentLevel.Floor.Box",
            "class": "/Script/Engine.BoxComponent",
        },
        "start": {"x": 0.0, "y": 0.0, "z": 200},
        "end": {"x": 0.0, "y": 0.0, "z": -200},
    }
    hit.to_tuple.assert_called_once_with()
    hit.export_text.assert_not_called()
    hit.get_editor_property.assert_not_called()


def test_none_is_the_only_no_blocking_hit_sentinel():
    result = read_hit_result(None)
    assert result["status"] == "no_hit"
    assert result["blocking_hit"] is result["start_penetrating"] is False
    assert set(result) == {
        "status",
        "blocking_hit",
        "start_penetrating",
        "distance_cm",
        "time",
        "location",
        "impact_point",
        "normal",
        "impact_normal",
        "actor",
        "component",
    }
    assert all(result[key] is None for key in result if key not in {"status", "blocking_hit", "start_penetrating"})


@pytest.mark.parametrize("layout", [0, 11, 15, 19, 20])
def test_unsupported_tuple_lengths_fail_explicitly(layout):
    hit = hit_with([None] * layout)
    with pytest.raises(ValueError, match="layout"):
        read_hit_result(hit)


@pytest.mark.parametrize("value", [None, [], native_values(), "HitResult(...)", {"blocking_hit": True}])
def test_reader_must_return_a_tuple(value):
    hit = hit_with(native_values())
    hit.to_tuple.return_value = value
    with pytest.raises(ValueError, match="layout"):
        read_hit_result(hit)


@pytest.mark.parametrize("field, value", [(0, 1), (0, None), (0, "true"), (1, 0), (1, 1), (1, None)])
def test_flags_must_be_actual_booleans(field, value):
    values = native_values()
    values[field] = value
    with pytest.raises(ValueError, match="flags"):
        read_hit_result(hit_with(values))


def test_non_none_nonblocking_result_is_an_error_not_a_miss():
    values = native_values()
    values[0] = False
    with pytest.raises(ValueError, match="must be blocking"):
        read_hit_result(hit_with(values))


@pytest.mark.parametrize(
    "field, value",
    [(2, True), (2, "0.5"), (2, float("nan")), (2, -0.1), (2, 1.1), (3, -1), (3, False), (3, float("inf"))],
)
def test_scalar_measurements_must_be_finite_numbers_in_native_range(field, value):
    values = native_values()
    values[field] = value
    with pytest.raises(ValueError, match="time|distance"):
        read_hit_result(hit_with(values))


@pytest.mark.parametrize("field", [4, 5, 6, 7, -2, -1])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), True, "1", None])
def test_each_decoded_vector_requires_finite_numeric_coordinates(field, invalid):
    values = native_values()
    values[field] = vector(x=invalid)
    with pytest.raises(ValueError, match="vector"):
        read_hit_result(hit_with(values))


@pytest.mark.parametrize("field", [4, 5, 6, 7, -2, -1])
@pytest.mark.parametrize("invalid", [None, {"x": 0, "y": 0, "z": 0}, SimpleNamespace(x=0, y=0)])
def test_vector_binding_attributes_must_exist(field, invalid):
    values = native_values()
    values[field] = invalid
    with pytest.raises(AttributeError):
        read_hit_result(hit_with(values))


def test_null_native_actor_and_component_identities_remain_null():
    values = native_values()
    values[9:11] = [None, None]
    result = read_hit_result(hit_with(values))
    assert result["actor"] is result["component"] is None
    assert result["status"] == "hit"


@pytest.mark.parametrize("field", [9, 10])
@pytest.mark.parametrize("method", ["get_name", "get_path_name", "get_class"])
def test_identity_api_errors_are_preserved(field, method):
    values = native_values()
    setattr(values[field], method, MagicMock(side_effect=RuntimeError("identity API interrupted")))
    with pytest.raises(RuntimeError, match="identity API interrupted"):
        read_hit_result(hit_with(values))


@pytest.mark.parametrize("field", [9, 10])
def test_missing_identity_binding_is_not_replaced_by_guessed_text(field):
    values = native_values()
    values[field] = SimpleNamespace(get_name=lambda: "Floor")
    with pytest.raises(AttributeError):
        read_hit_result(hit_with(values))


@pytest.mark.parametrize("field", [9, 10])
def test_missing_native_class_identity_fails_explicitly(field):
    values = native_values()
    values[field].get_class = lambda: None
    with pytest.raises(AttributeError):
        read_hit_result(hit_with(values))


@pytest.mark.parametrize("field", [9, 10])
@pytest.mark.parametrize("attribute, value", [("name", ""), ("path", None), ("class_path", 1)])
def test_native_identity_values_must_be_nonempty_strings(field, attribute, value):
    values = native_values()
    setattr(values[field], attribute, value)
    with pytest.raises(ValueError, match="identity"):
        read_hit_result(hit_with(values))


def test_reader_exception_is_preserved_without_text_or_property_fallback():
    hit = hit_with(native_values())
    hit.to_tuple.side_effect = RuntimeError("native break failed")
    with pytest.raises(RuntimeError, match="native break failed"):
        read_hit_result(hit)
    hit.export_text.assert_not_called()
    hit.get_editor_property.assert_not_called()


@pytest.mark.parametrize("reader", [None, "to_tuple"])
def test_missing_native_reader_fails_without_text_or_property_fallback(reader):
    hit = hit_with(native_values())
    hit.to_tuple = reader
    with pytest.raises(RuntimeError, match="to_tuple"):
        read_hit_result(hit)
    hit.export_text.assert_not_called()
    hit.get_editor_property.assert_not_called()


def test_no_reader_attribute_fails_without_property_fallback():
    hit = SimpleNamespace(
        export_text=MagicMock(side_effect=AssertionError("No text fallback")),
        get_editor_property=MagicMock(side_effect=AssertionError("No property fallback")),
    )
    with pytest.raises(RuntimeError, match="to_tuple"):
        read_hit_result(hit)
    hit.export_text.assert_not_called()
    hit.get_editor_property.assert_not_called()


def test_initial_overlap_preserves_native_flags_and_measurements():
    values = native_values()
    values[1:4] = [True, 0.0, 0.0]
    values[4:8] = [vector(z=200), vector(z=200), vector(), vector()]
    result = read_hit_result(hit_with(values))
    assert result["start_penetrating"] is True and result["blocking_hit"] is True
    assert result["distance_cm"] == result["time"] == 0.0
    assert result["location"] == result["impact_point"] == {"x": 0.0, "y": 0.0, "z": 200}


@pytest.mark.parametrize("outcome", ["target", "other_path", "miss", "reader_error"])
def test_existing_playtest_consumer_uses_tuple_when_hit_properties_are_unavailable(monkeypatch, outcome):
    runtime_path = (
        Path(__file__).resolve().parents[1]
        / "src/dcc_mcp_unreal/skills/unreal-playtest-agent/scripts/_playtest_runtime.py"
    )
    module_name = "_spatial_consumer_regression_runtime"
    spec = importlib.util.spec_from_file_location(module_name, runtime_path)
    runtime = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, runtime)
    spec.loader.exec_module(runtime)
    target = NativeObject("Target", "/Game/Fixture.Fixture:PersistentLevel.Target", "/Script/Engine.Actor")
    target.get_actor_location = lambda: vector(z=-200)
    player = NativeObject("Player", "/Game/Fixture.Fixture:PersistentLevel.Player", "/Script/Engine.Pawn")
    controller = SimpleNamespace(get_player_view_point=lambda: (vector(z=200), object()))
    values = native_values()
    values[9] = (
        target
        if outcome == "target"
        else NativeObject("Target", "/Game/Other.Other:PersistentLevel.Target", "/Script/Engine.Actor")
    )
    hit = hit_with(values)
    if outcome == "reader_error":
        hit.to_tuple.side_effect = RuntimeError("native break unavailable")
    trace = MagicMock(return_value=None if outcome == "miss" else hit)
    debug_none = object()
    unreal = SimpleNamespace(
        SystemLibrary=SimpleNamespace(line_trace_single=trace),
        TraceTypeQuery=SimpleNamespace(cast=lambda index: SimpleNamespace(value=index)),
        DrawDebugTrace=SimpleNamespace(NONE=debug_none),
    )
    result = runtime._line_of_fire(unreal, controller, player, target)
    assert result is {"target": True, "other_path": False, "miss": True, "reader_error": None}[outcome]
    args = trace.call_args.args
    assert args[0] is player and args[5] == [player]
    assert args[3].value == 0 and args[6] is debug_none
    hit.get_editor_property.assert_not_called()
    hit.export_text.assert_not_called()
