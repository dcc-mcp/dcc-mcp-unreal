"""Mocked contract tests, not native Unreal solver acceptance."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
import yaml

from dcc_mcp_unreal import pcg_pathfinding as pf


def _request():
    return {
        "point_cloud": [{"position": [0, 0, 0]}, {"position": [100, 0, 0]}],
        "start": {"location": [0, 0, 0]},
        "goal": {"location": [100, 0, 0]},
        "settings": {"search_distance": 110},
    }


def _input_endpoints(request):
    request["start"] = {"attribute": "Starts", "values": [[0, 0, 0]]}
    request["goal"] = {"attribute": "Goals", "values": [[100, 0, 0], [200, 0, 0]]}


def _host(*, missing=(), package="/Engine/Transient", corrupt=None, malformed_copy=False, pin_count=1):
    events = []
    outermost = SimpleNamespace(get_path_name=lambda: package)

    class Native:
        def get_outermost(self):
            return outermost

        def get_editor_property(self, name):
            return self.properties[name]

    class Selector:
        def __init__(self):
            self.name = "None"

        def set_attribute_name(self, name):
            self.name = name
            return True

        def get_attribute_name(self):
            return self.name

    class Vector:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z

    class Settings(Native):
        def __init__(self):
            events.append("construct_settings")
            fields = pf._OPTIONS | {
                "use_path_traces",
                "start",
                "goal",
                "start_locations_as_input",
                "goal_locations_as_input",
                "start_location_attribute",
                "goal_location_attribute",
            }
            self.properties = {field: None for field in fields - set(missing)}

        def set_editor_property(self, name, value):
            events.append(("write", name))
            if name not in self.properties:
                raise RuntimeError("unexposed")
            self.properties[name] = -1 if corrupt == name else value

    def pin(label):
        properties = Native()
        properties.properties = {
            "label": label,
            "allowed_types": "HostObservedDataType",
            "allow_multiple_data": True,
            "allow_multiple_connections": False,
        }
        value = Native()
        value.properties = {"properties": properties}
        return value

    class Graph(Native):
        def __init__(self):
            events.append("construct_graph")

        def add_node_copy(self, settings):
            events.append("copy_node")
            copied = copy.deepcopy(settings)
            node = Native()
            inputs = [pin("PointsNative") for _ in range(pin_count)]
            for side in ("start", "goal"):
                if copied.properties[side + "_locations_as_input"]:
                    inputs.append(pin(side + "Native"))
            node.properties = {
                "input_pins": inputs,
                "output_pins": [pin("SplineNative" if copied.properties["output_as_spline"] else "PointsOutNative")],
            }
            node.get_settings = lambda: copied
            return node if malformed_copy else (node, copied)

    return SimpleNamespace(
        PCGPathfindingSettings=Settings,
        PCGGraph=Graph,
        PCGAttributePropertyInputSelector=Selector,
        PCGPathfindingCostFunctionMode=Enum("Cost", "DISTANCE FITNESS_SCORE COST_MULTIPLIER"),
        PCGPathfindingSplineMode=Enum("Spline", "CURVE LINEAR"),
        PCGPathfindingGoalMappingMode=Enum("Mapping", "HOST_TEST_MAPPING"),
        Vector=Vector,
        events=events,
        SystemLibrary=SimpleNamespace(get_engine_version=lambda: "custom-build"),
    )


def test_transient_configuration_not_path_execution():
    request = _request()
    original = copy.deepcopy(request)
    host = _host()
    result = pf.preflight_pathfinding(host, **request)
    assert result["configuration_verified"] is True
    assert result["execution_verified"] is False
    assert result["generation_started"] is False
    assert result["persistent_assets_modified"] is False
    assert result["saved"] is False
    assert result["path_result"] == {"status": "not_executed", "complete": None, "partial": None, "reachable": None}
    assert result["input_summary"]["input_data_materialized"] is False
    assert result["settings_readback"]["start"] == [0, 0, 0]
    assert result["settings_readback"]["use_path_traces"] is False
    assert result["input_pins"][0]["label"] == "PointsNative"
    assert result["output_pins"][0]["label"] == "PointsOutNative"
    assert host.events.count("construct_graph") == 1
    assert request == original
    json.dumps(result, allow_nan=False)


def test_attribute_endpoints_and_configured_output_pins():
    request = _request()
    _input_endpoints(request)
    request["settings"].update(output_as_spline=True, spline_mode="LINEAR", goal_mapping_mode="HOST_TEST_MAPPING")
    result = pf.preflight_pathfinding(_host(), **request)
    assert [pin["label"] for pin in result["input_pins"]] == ["PointsNative", "startNative", "goalNative"]
    assert result["output_pins"][0]["label"] == "SplineNative"
    assert result["settings_readback"]["start_location_attribute"] == "Starts"
    assert result["settings_readback"]["goal_mapping_mode"] == "HOST_TEST_MAPPING"
    assert result["input_summary"]["goal_count"] == 2
    assert result["version_used_as_gate"] is False


@pytest.mark.parametrize("version", ["5.2.0", "5.5.0", "5.7.0", "6.0.0"])
def test_optional_property_is_gated_by_presence_not_version(version):
    request = _request()
    _input_endpoints(request)
    request["settings"]["goal_mapping_mode"] = "HOST_TEST_MAPPING"
    host = _host(missing={"goal_mapping_mode"})
    host.SystemLibrary.get_engine_version = lambda: version
    with pytest.raises(pf.PathfindingHostError, match="goal_mapping_mode"):
        pf.preflight_pathfinding(host, **request)
    assert host.events == ["construct_settings"]


@pytest.mark.parametrize("mode,cost", [("FITNESS_SCORE", 0.4), ("COST_MULTIPLIER", 2)])
def test_numeric_cost_modes_and_case_insensitive_names(mode, cost):
    request = _request()
    request["settings"].update(cost_function_mode=mode, cost_attribute="Cost")
    for point in request["point_cloud"]:
        point["attributes"] = {"cost": cost}
    result = pf.preflight_pathfinding(_host(), **request)
    assert result["settings_readback"]["cost_function_mode"] == mode
    assert result["settings_readback"]["cost_attribute"] == "Cost"


def test_empty_cloud_and_cost_heuristic_warnings_do_not_invent_results():
    request = _request()
    request["point_cloud"] = []
    result = pf.preflight_pathfinding(_host(), **request)
    assert "empty" in result["warnings"][0]
    assert result["path_result"]["reachable"] is None
    request = _request()
    request["settings"].update(cost_function_mode="COST_MULTIPLIER", cost_attribute="Cost", heuristic_weight=2)
    for point in request["point_cloud"]:
        point["attributes"] = {"Cost": 0.5}
    result = pf.preflight_pathfinding(_host(), **request)
    assert len(result["warnings"]) == 2
    assert "2 supplied costs" in result["warnings"][0]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, "4", 10**400, 1e10])
def test_bad_coordinates_rejected_before_native_construction(value):
    request = _request()
    request["point_cloud"][0]["position"][0] = value
    host = _host()
    with pytest.raises(pf.PathfindingValidationError):
        pf.preflight_pathfinding(host, **request)
    assert host.events == []


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"search_distance": 0},
        {"search_distance": -1},
        {"search_distance": True},
        {"search_distance": 1, "use_path_traces": True},
        {"search_distance": 1, "unknown": 1},
        {"search_distance": 1, "cost_function_mode": "unknown"},
        {"search_distance": 1, "cost_attribute": "Cost"},
        {"search_distance": 1, "cost_function_mode": "FITNESS_SCORE"},
        {"search_distance": 1, "heuristic_weight": -1},
        {"search_distance": 1, "heuristic_weight": 101},
        {"search_distance": 1, "maximum_fitness_penalty_factor": float("nan")},
        {"search_distance": 1, "accept_partial_path": 1},
        {"search_distance": 1, "seed": 1.1},
        {"search_distance": 1, "seed": 2**31},
        {"search_distance": 1, "spline_mode": "CURVE"},
        {"search_distance": 1, "goal_mapping_mode": "HOST_TEST_MAPPING"},
    ],
)
def test_invalid_settings_rejected(settings):
    request = _request()
    request["settings"] = settings
    with pytest.raises(pf.PathfindingValidationError):
        pf.validate_pathfinding_request(**request)


@pytest.mark.parametrize(
    "endpoint",
    [
        None,
        [],
        {},
        {"location": [0, 0]},
        {"location": [0, 0, 0], "attribute": "A"},
        {"attribute": "$Position", "values": [[0, 0, 0]]},
        {"attribute": "None", "values": [[0, 0, 0]]},
        {"attribute": "A", "values": []},
        {"attribute": "A", "values": [[0, 0, 0]] * 65},
    ],
)
def test_invalid_endpoints_rejected(endpoint):
    request = _request()
    request["start"] = endpoint
    with pytest.raises(pf.PathfindingValidationError):
        pf.validate_pathfinding_request(**request)


@pytest.mark.parametrize(
    "attributes",
    [
        {},
        {"Cost": -0.1},
        {"Cost": 1.1},
        {"Cost": True},
        {"Cost": float("nan")},
        {"Cost": [1, 0, 0]},
        {"Cost": 0, "cost": 1},
    ],
)
def test_missing_invalid_or_ambiguous_fitness_cost(attributes):
    request = _request()
    request["settings"].update(cost_function_mode="FITNESS_SCORE", cost_attribute="Cost")
    request["point_cloud"] = [{"position": [0, 0, 0], "attributes": attributes}]
    with pytest.raises(pf.PathfindingValidationError):
        pf.validate_pathfinding_request(**request)


def test_point_and_attribute_bounds():
    request = _request()
    request["point_cloud"] *= 2049
    with pytest.raises(pf.PathfindingValidationError, match="4096"):
        pf.validate_pathfinding_request(**request)
    request["point_cloud"] = [{"position": [0, 0, 0], "attributes": {f"A{i}": i for i in range(17)}}]
    with pytest.raises(pf.PathfindingValidationError, match="16"):
        pf.validate_pathfinding_request(**request)


@pytest.mark.parametrize(
    "host,match",
    [
        (_host(package="/Game/Existing"), "Transient"),
        (_host(corrupt="search_distance"), "readback differs"),
        (_host(malformed_copy=True), "result shape"),
        (_host(pin_count=65), "64-pin"),
        (_host(pin_count=0), "no inspectable"),
        (SimpleNamespace(), "preflight failed"),
    ],
)
def test_host_failure_never_becomes_configuration_success(host, match):
    with pytest.raises(pf.PathfindingHostError, match=match):
        pf.preflight_pathfinding(host, **_request())
    if match == "Transient":
        assert host.events == ["construct_settings"]


def test_missing_enum_member_rejected_before_writes():
    request = _request()
    _input_endpoints(request)
    request["settings"]["goal_mapping_mode"] = "NOT_ON_HOST"
    host = _host()
    with pytest.raises(pf.PathfindingHostError, match="enum member"):
        pf.preflight_pathfinding(host, **request)
    assert host.events == ["construct_settings"]


def test_optional_mapping_discovery_without_requesting_unsupported_field():
    result = pf.preflight_pathfinding(_host(), **_request())
    assert result["optional_goal_mapping"]["enum_members"] == ["HOST_TEST_MAPPING"]
    result = pf.preflight_pathfinding(_host(missing={"goal_mapping_mode"}), **_request())
    assert result["configuration_verified"] is True
    assert result["optional_goal_mapping"]["property_readable"] is False
    assert result["optional_goal_mapping"]["enum_members"] == []


def test_selector_setter_noop_is_readback_verified():
    host = _host()
    host.PCGAttributePropertyInputSelector.set_attribute_name = lambda self, name: False
    request = _request()
    _input_endpoints(request)
    with pytest.raises(pf.PathfindingHostError, match="selector readback"):
        pf.preflight_pathfinding(host, **request)
    assert host.events == ["construct_settings"]


def test_host_errors_and_pin_text_are_bounded():
    host = _host()

    def broken(self, name):
        raise RuntimeError("x" * 10000)

    host.PCGPathfindingSettings.get_editor_property = broken
    with pytest.raises(pf.PathfindingHostError) as error:
        pf.preflight_pathfinding(host, **_request())
    assert len(str(error.value)) < 400


@pytest.mark.parametrize("expected,actual", [(True, 1), (False, 0), (1, True), (1.0, "1"), (1, float("nan"))])
def test_native_scalar_readback_does_not_coerce_types(expected, actual):
    with pytest.raises(pf.PathfindingHostError):
        pf._readback(SimpleNamespace(get_editor_property=lambda name: actual), "test", expected)


def _skill():
    path = Path("src/dcc_mcp_unreal/skills/unreal-pcg-pathfinding/scripts/preflight_pcg_pathfinding.py")
    spec = importlib.util.spec_from_file_location("_test_pcg_pathfinding_skill", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_import_is_lazy_and_no_host_is_not_success(monkeypatch):
    monkeypatch.setitem(sys.modules, "unreal", None)
    result = _skill().preflight_pcg_pathfinding(**_request())
    assert result["success"] is False
    assert result["context"]["error_kind"] == "host_unavailable"
    assert result["context"]["execution_verified"] is False


def test_skill_success_and_unknown_top_level_args(monkeypatch):
    host = _host()
    monkeypatch.setitem(sys.modules, "unreal", host)
    skill = _skill()
    result = skill.preflight_pcg_pathfinding(**_request())
    assert result["success"] is True
    assert result["context"]["path_result"]["status"] == "not_executed"
    host.events.clear()
    result = skill.preflight_pcg_pathfinding(**_request(), save=True)
    assert result["success"] is False
    assert result["context"]["error_kind"] == "invalid_input"
    assert host.events == []


def test_catalog_script_runner_invokes_the_preflight_entry(monkeypatch):
    from dcc_mcp_unreal.skill_runner import run_skill_script

    monkeypatch.setitem(sys.modules, "unreal", _host())
    script = "src/dcc_mcp_unreal/skills/unreal-pcg-pathfinding/scripts/preflight_pcg_pathfinding.py"
    result = run_skill_script(script, _request())
    assert result["success"] is True
    assert result["context"]["configuration_verified"] is True
    assert result["context"]["execution_verified"] is False


def test_schema_examples_runtime_contract_and_affinity():
    path = Path("src/dcc_mcp_unreal/skills/unreal-pcg-pathfinding/tools.yaml")
    tool = yaml.safe_load(path.read_text())["tools"][0]
    schema = tool["input_schema"]
    jsonschema.Draft7Validator.check_schema(schema)
    for example in tool["call_examples"]:
        jsonschema.validate(example["arguments"], schema)
        pf.validate_pathfinding_request(**example["arguments"])
    assert tool["affinity"] == "main"
    assert tool["enforce_thread_affinity"] is True
    assert tool["read_only"] is False
    for request in [dict(_request(), save=True), dict(_request(), start={"attribute": "A", "values": []})]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(request, schema)
