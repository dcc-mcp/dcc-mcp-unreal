"""Contracts for native DynamicMesh skin weight access; no engine required."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

SKILL = Path(__file__).resolve().parents[1] / "src/dcc_mcp_unreal/skills/unreal-geometry-script"


@pytest.fixture
def runtime(monkeypatch):
    class DynamicMesh:
        def get_path_name(self):
            return "/Engine/Transient.Mesh"

    class Profile:
        profile_name = "Default"

        def set_editor_property(self, name, value):
            setattr(self, name, value)

    class Weight:
        def __init__(self, bone_index, weight):
            self.bone_index, self.weight = bone_index, weight

    mesh = DynamicMesh()
    api = MagicMock()
    api.set_vertex_bone_weights.return_value = mesh, True
    api.get_vertex_bone_weights.return_value = mesh, [Weight(3, 0.749996), Weight(7, 0.250004)], True
    unreal = types.SimpleNamespace(
        DynamicMesh=DynamicMesh,
        GeometryScriptBoneWeightProfile=Profile,
        GeometryScriptBoneWeight=Weight,
        GeometryScript_BoneWeights=api,
        GeometryScript_MeshQueries=types.SimpleNamespace(is_valid_vertex_id=lambda mesh, vertex: vertex in (0, 3)),
        find_object=lambda outer, path: mesh if path == mesh.get_path_name() else None,
    )
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    spec = importlib.util.spec_from_file_location(
        "_vertex_weights_contract", SKILL / "scripts/_dynamic_mesh_weights.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, unreal, api


def test_writer_preserves_profile_and_reports_sdk_readback(runtime):
    module, unreal, api = runtime
    result = module.set_vertex_bone_weights(
        mesh_path="/Engine/Transient.Mesh",
        vertex_id=3,
        bone_weights=[{"bone_index": 3, "weight": 0.75}, {"bone_index": 7, "weight": 0.25}],
        profile_name="Preview",
    )
    assert result["success"] is True
    assert result["context"]["bone_weights"][0]["weight"] == 0.749996
    create = api.mesh_create_bone_weights.call_args
    assert create.kwargs["replace_existing_profile"] is False
    assert create.kwargs["profile"].profile_name == "Preview"
    assert api.method_calls[0][0] == "mesh_create_bone_weights"
    assert api.method_calls[-1][0] == "get_vertex_bone_weights"


@pytest.mark.parametrize(
    "weights",
    [
        [],
        [{"bone_index": 0, "weight": float("nan")}],
        [{"bone_index": 0, "weight": float("inf")}],
        [{"bone_index": 0, "weight": -1}],
        [{"bone_index": 0, "weight": 0.5}],
        [{"bone_index": True, "weight": 1}],
        [{"bone_index": 65536, "weight": 1}],
        [{"bone_index": 0, "weight": True}],
        [{"bone_index": 0, "weight": 1, "extra": 0}],
        [{"bone_index": 0, "weight": 0.5}, {"bone_index": 0, "weight": 0.5}],
        [{"bone_index": i, "weight": 1 / 13} for i in range(13)],
    ],
)
def test_invalid_weights_do_not_mutate(runtime, weights):
    module, unreal, api = runtime
    result = module.set_vertex_bone_weights(mesh_path="/Engine/Transient.Mesh", vertex_id=0, bone_weights=weights)
    assert result["success"] is False
    api.mesh_create_bone_weights.assert_not_called()
    api.set_vertex_bone_weights.assert_not_called()


@pytest.mark.parametrize(
    "path, vertex, profile",
    [
        ("", 0, None),
        ("/Missing", 0, None),
        ("/Engine/Transient.Mesh", 1, None),
        ("/Engine/Transient.Mesh", True, None),
        ("/Engine/Transient.Mesh", -1, None),
        ("/Engine/Transient.Mesh", 0, ""),
        ("/Engine/Transient.Mesh", 0, "None"),
        ("/Engine/Transient.Mesh", 0, "two words"),
    ],
)
def test_invalid_target_or_profile_does_not_mutate(runtime, path, vertex, profile):
    module, unreal, api = runtime
    result = module.set_vertex_bone_weights(
        mesh_path=path, vertex_id=vertex, bone_weights=[{"bone_index": 0, "weight": 1}], profile_name=profile
    )
    assert result["success"] is False
    api.mesh_create_bone_weights.assert_not_called()


def test_reader_uses_default_profile_without_mutation(runtime):
    module, unreal, api = runtime
    result = module.get_vertex_bone_weights(mesh_path="/Engine/Transient.Mesh", vertex_id=0)
    assert result["success"] is True
    assert result["context"]["profile_name"] == "Default"
    api.mesh_create_bone_weights.assert_not_called()
    api.set_vertex_bone_weights.assert_not_called()


def test_missing_profile_and_sdk_rejection_are_errors(runtime):
    module, unreal, api = runtime
    api.get_vertex_bone_weights.return_value = None, [], False
    assert module.get_vertex_bone_weights(mesh_path="/Engine/Transient.Mesh", vertex_id=0)["success"] is False
    api.set_vertex_bone_weights.return_value = None, False
    assert (
        module.set_vertex_bone_weights(
            mesh_path="/Engine/Transient.Mesh", vertex_id=0, bone_weights=[{"bone_index": 0, "weight": 1}]
        )["success"]
        is False
    )


def test_missing_plugin_fails_without_mutation(runtime):
    module, unreal, api = runtime
    del unreal.GeometryScript_BoneWeights
    assert module.get_vertex_bone_weights(mesh_path="/Engine/Transient.Mesh", vertex_id=0)["success"] is False
    api.mesh_create_bone_weights.assert_not_called()


def test_native_zero_weight_padding_is_removed_from_read_and_write_results(runtime):
    module, unreal, api = runtime
    weight = unreal.GeometryScriptBoneWeight
    api.get_vertex_bone_weights.return_value = (
        None,
        [weight(0, 0), weight(0, 0), weight(0, 0.7499961853027344), weight(1, 0.2500038146972656)],
        True,
    )
    expected = [
        {"bone_index": 0, "weight": 0.7499961853027344},
        {"bone_index": 1, "weight": 0.2500038146972656},
    ]
    read = module.get_vertex_bone_weights(mesh_path="/Engine/Transient.Mesh", vertex_id=0)
    write = module.set_vertex_bone_weights(
        mesh_path="/Engine/Transient.Mesh",
        vertex_id=0,
        bone_weights=[{"bone_index": 0, "weight": 0.75}, {"bone_index": 1, "weight": 0.25}],
    )
    assert read["context"]["bone_weights"] == expected
    assert write["context"]["bone_weights"] == expected


@pytest.mark.parametrize(
    "native_weights",
    [
        [(0, float("nan"))],
        [(0, float("inf"))],
        [(65536, 1)],
        [(-1, 1)],
        [(0, -1)],
    ],
)
def test_unrepresentable_native_readback_is_an_error(runtime, native_weights):
    module, unreal, api = runtime
    api.get_vertex_bone_weights.return_value = (
        None,
        [unreal.GeometryScriptBoneWeight(index, value) for index, value in native_weights],
        True,
    )
    result = module.get_vertex_bone_weights(mesh_path="/Engine/Transient.Mesh", vertex_id=0)
    assert result["success"] is False
    api.set_vertex_bone_weights.assert_not_called()


@pytest.mark.parametrize(
    "native_weights, expected_count",
    [
        ([(0, 0.5)], 1),
        ([(0, 0.5), (0, 0.4)], 2),
        ([(0, 0)], 0),
        ([], 0),
        ([(index, 0.1) for index in range(13)], 13),
    ],
)
def test_unnormalized_native_readback_is_reported_not_rejected(runtime, native_weights, expected_count):
    module, unreal, api = runtime
    api.get_vertex_bone_weights.return_value = (
        None,
        [unreal.GeometryScriptBoneWeight(index, value) for index, value in native_weights],
        True,
    )
    result = module.get_vertex_bone_weights(mesh_path="/Engine/Transient.Mesh", vertex_id=0)
    assert result["success"] is True
    context = result["context"]
    assert context["influence_count"] == expected_count
    assert context["normalized"] is False
    assert context["bone_weights"] == [
        {"bone_index": index, "weight": float(value)} for index, value in native_weights if value != 0
    ]


# 21845 / 65536 is what native 16 bit quantization leaves for 1/3. It sums to
# 0.9999847412109375, i.e. 1.5e-5 away from 1: inside the readback tolerance of
# 1e-4 but far outside the 1e-6 input tolerance that a readback must not reuse.
QUANTIZED_THIRD = 21845 / 65536


@pytest.mark.parametrize(
    "native_weights, expected_normalized",
    [
        ([(3, QUANTIZED_THIRD), (4, QUANTIZED_THIRD), (5, QUANTIZED_THIRD)], True),
        ([(3, 0.7499961853027344), (7, 0.2500038146972656)], True),
        ([(3, 0.2499), (4, 0.2499), (5, 0.2499), (6, 0.2499)], False),
    ],
)
def test_quantized_readback_is_reported_without_failing_the_write(runtime, native_weights, expected_normalized):
    module, unreal, api = runtime
    api.get_vertex_bone_weights.return_value = (
        None,
        [unreal.GeometryScriptBoneWeight(index, value) for index, value in native_weights],
        True,
    )
    written = [{"bone_index": 3, "weight": 0.5}, {"bone_index": 4, "weight": 0.5}]
    result = module.set_vertex_bone_weights(mesh_path="/Engine/Transient.Mesh", vertex_id=0, bone_weights=written)
    # The vertex was written, so a drift in the readback must not look like a failure.
    assert result["success"] is True
    assert result["postcondition"]["verified"] is expected_normalized
    assert result["context"]["readback_error"] is None
    assert result["context"]["normalized"] is expected_normalized
    assert result["context"]["bone_weights"] == [
        {"bone_index": index, "weight": value} for index, value in native_weights
    ]
    api.set_vertex_bone_weights.assert_called_once()


def test_quantized_readback_stays_visible_to_the_reader(runtime):
    module, unreal, api = runtime
    api.get_vertex_bone_weights.return_value = (
        None,
        [unreal.GeometryScriptBoneWeight(index, QUANTIZED_THIRD) for index in (3, 4, 5)],
        True,
    )
    result = module.get_vertex_bone_weights(mesh_path="/Engine/Transient.Mesh", vertex_id=0)
    assert result["success"] is True
    assert result["context"]["normalized"] is True
    total = result["context"]["weight_sum"]
    assert result["context"]["sum_abs_tol"] == 1e-4
    assert 1e-6 < abs(total - 1.0) < 1e-4


def test_unrepresentable_readback_does_not_turn_a_write_into_a_failure(runtime):
    module, unreal, api = runtime
    api.get_vertex_bone_weights.return_value = None, [unreal.GeometryScriptBoneWeight(0, float("nan"))], True
    result = module.set_vertex_bone_weights(
        mesh_path="/Engine/Transient.Mesh", vertex_id=0, bone_weights=[{"bone_index": 0, "weight": 1}]
    )
    assert result["success"] is True
    assert result["postcondition"]["verified"] is False
    assert "Native weight" in result["context"]["readback_error"]
    assert result["context"]["bone_weights"] == []
    # The write already landed, so it must still be reported as a write.
    api.set_vertex_bone_weights.assert_called_once()


def test_manifest_declares_closed_schemas_and_editor_affinity():
    tools = yaml.safe_load((SKILL / "tools.yaml").read_text())["tools"]
    assert [tool["name"] for tool in tools] == ["get_vertex_bone_weights", "set_vertex_bone_weights"]
    for tool in tools:
        assert tool["input_schema"]["additionalProperties"] is False
        assert tool["affinity"] == "main" and tool["enforce_thread_affinity"] is True
    assert tools[0]["read_only"] is True and tools[1]["read_only"] is False


@pytest.mark.parametrize("tool", [0, 1])
def test_schema_rejects_the_reserved_profile_name(tool):
    tools = yaml.safe_load((SKILL / "tools.yaml").read_text())["tools"]
    schema = tools[tool]["input_schema"]
    arguments = {"mesh_path": "/Engine/Transient.Mesh", "vertex_id": 0}
    if tool:
        arguments["bone_weights"] = [{"bone_index": 0, "weight": 1}]
    for reserved in ("None", "none", "NONE", "nOnE"):
        assert not jsonschema.Draft202012Validator(schema).is_valid({**arguments, "profile_name": reserved})
    assert jsonschema.Draft202012Validator(schema).is_valid({**arguments, "profile_name": "Preview"})


def test_output_schema_declares_the_readback_diagnostics():
    tools = yaml.safe_load((SKILL / "tools.yaml").read_text())["tools"]
    for tool in tools:
        context = tool["output_schema"]["properties"]["context"]["properties"]
        assert {"bone_weights", "influence_count", "weight_sum", "normalized", "sum_abs_tol"} <= set(context)


def test_separate_entry_scripts_dispatch_read_and_write(runtime, monkeypatch):
    helper, unreal, api = runtime
    monkeypatch.setitem(sys.modules, "_dynamic_mesh_weights", helper)
    for name in ("get_vertex_bone_weights", "set_vertex_bone_weights"):
        spec = importlib.util.spec_from_file_location(name, SKILL / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        arguments = {"mesh_path": "/Engine/Transient.Mesh", "vertex_id": 0}
        if name.startswith("set"):
            arguments["bone_weights"] = [{"bone_index": 0, "weight": 1}]
        result = getattr(module, name)(**arguments)
        assert result["success"] is True
        if name.startswith("get"):
            api.set_vertex_bone_weights.assert_not_called()
        else:
            api.set_vertex_bone_weights.assert_called_once()
