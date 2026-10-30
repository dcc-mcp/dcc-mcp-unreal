"""Typed grammar authoring tests with fakes, not native grammar execution."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from dcc_mcp_unreal.pcg_grammar import GrammarCodecError, prepare_grammar_property
from dcc_mcp_unreal.pcg_graph import PcgGraphError, graph_operation
from tests.test_pcg_graph import Host, Object, PCGSettings


class Struct:
    def __init__(self, **properties):
        self.properties = properties

    def get_editor_property(self, name):
        return self.properties[name]

    def set_editor_property(self, name, value):
        if name not in self.properties:
            raise AttributeError(name)
        self.properties[name] = value

    def copy(self):
        return copy.deepcopy(self)

    def export_text(self):
        def plain(value):
            if isinstance(value, Struct):
                return {key: plain(item) for key, item in value.properties.items()}
            if isinstance(value, list):
                return [plain(item) for item in value]
            return value

        return json.dumps(plain(self), sort_keys=True)


class Vector4(Struct):
    def __init__(self, x=0.0, y=0.0, z=0.0, w=0.0):
        super().__init__(x=x, y=y, z=z, w=w)


class PCGAttributePropertyInputSelector(Struct):
    def __init__(self):
        super().__init__(name="@Last", selection="ATTRIBUTE", extra_names=[])

    def set_attribute_name(self, name):
        self.properties["name"] = name
        return True

    def get_attribute_name(self):
        return self.properties["name"]

    def get_name(self):
        return self.properties["name"]

    def get_selection(self):
        return self.properties["selection"]

    def get_extra_names(self):
        return self.properties["extra_names"]


class PCGGrammarSelection(Struct):
    def __init__(self):
        super().__init__(
            grammar_as_attribute=False, grammar_string="", grammar_attribute=PCGAttributePropertyInputSelector()
        )


class PCGSubdivisionSubmodule(Struct):
    def __init__(self):
        super().__init__(symbol="None", size=0.0, scalable=False, debug_color=Vector4(1.0, 1.0, 1.0, 1.0))


class PCGSubdivideSplineSettings(PCGSettings):
    def __init__(self):
        super().__init__()
        self.properties.update(
            grammar_selection=PCGGrammarSelection(),
            modules_info=[],
            module_info_as_input=False,
            module_height=100.0,
            accept_incomplete_subdivision=False,
        )

    def get_class(self):
        return Object("/Script/PCG.PCGSubdivideSplineSettings")


class GrammarHost(Host):
    PCGSubdivideSplineSettings = PCGSubdivideSplineSettings
    PCGGrammarSelection = PCGGrammarSelection
    PCGSubdivisionSubmodule = PCGSubdivisionSubmodule
    PCGAttributePropertyInputSelector = PCGAttributePropertyInputSelector
    Vector4 = Vector4


@pytest.fixture
def fixture():
    host = GrammarHost()
    node, settings = host.assets["/Game/Test"].add_node_of_type(PCGSubdivideSplineSettings)
    return host, node, settings


def literal(text="[A,B]*"):
    return {"grammar_as_attribute": False, "grammar_string": text}


def modules():
    return [
        {"symbol": "A", "size": 200, "scalable": False},
        {"symbol": "B", "size": 50.0, "scalable": True, "debug_color": [0.1, 0.2, 0.3, 1.0]},
    ]


def update(fixture, **changes):
    host, node, _ = fixture
    return graph_operation(host, "update_node", "/Game/Test", node_id=node.path, settings=changes)


def inspect(fixture, names=None):
    host, _, _ = fixture
    return graph_operation(host, "inspect", "/Game/Test", settings_names=names or ["grammar_selection", "modules_info"])


def values(fixture, result):
    return next(row for row in result["nodes"] if row["node_id"] == fixture[1].path)["settings"]


@pytest.mark.parametrize("text", ["[A,B]*", "{[A,B]:2,[B,A]:1}+,<A,B>", "[Missing]3", "[bad syntax"])
def test_literal_is_preserved_without_claiming_engine_validation(fixture, text):
    result = update(fixture, grammar_selection=literal(text), modules_info=modules(), seed=42)
    observed = values(fixture, result)
    assert observed["grammar_selection"]["value"]["grammar_string"] == text
    assert observed["modules_info"]["value"][0]["size"] == 200.0
    assert observed["modules_info"]["value"][1]["debug_color"] == [0.1, 0.2, 0.3, 1.0]
    assert observed["seed"]["value"] == 42
    assert result["grammar_validation"] == {
        "settings_readback_verified": True,
        "syntax_verified": False,
        "symbol_references_verified": False,
        "geometric_fit_verified": False,
        "asset_mapping_verified": False,
    }
    assert result["generation_status"] == "not_requested"
    assert not result["execution_verified"] and not result["saved"]
    assert not fixture[0].saved


def test_attribute_selection_retains_inactive_literal_and_inspects_actual_selector(fixture):
    update(fixture, grammar_selection=literal("[A]*"))
    result = update(fixture, grammar_selection={"grammar_as_attribute": True, "grammar_attribute": "Grammar"})
    observed = values(fixture, result)["grammar_selection"]["value"]
    assert observed["grammar_as_attribute"] and observed["grammar_string"] == "[A]*"
    assert observed["grammar_attribute"] == {"name": "Grammar", "selection": "ATTRIBUTE", "extra_names": []}
    result = update(fixture, grammar_selection=literal("B+"))
    assert values(fixture, result)["grammar_selection"]["value"]["grammar_attribute"]["name"] == "Grammar"


@pytest.mark.parametrize(
    "descriptor",
    [
        None,
        "[A]",
        {},
        {"grammar_as_attribute": 1, "grammar_attribute": "Grammar"},
        {"grammar_as_attribute": False},
        {"grammar_as_attribute": False, "grammar_string": "A", "grammar_attribute": "Unused"},
        literal(""),
        literal(" \n"),
        literal("A\x00B"),
        literal("A" * 4097),
        {"grammar_as_attribute": True, "grammar_attribute": "None"},
        {"grammar_as_attribute": True, "grammar_attribute": "$Position.X"},
        {"grammar_as_attribute": True, "grammar_attribute": "A" * 65},
        {"grammar_as_attribute": True, "grammar_attribute": {"name": "Grammar"}},
    ],
)
def test_bad_grammar_descriptors_reject_before_transaction(fixture, descriptor):
    before = inspect(fixture)
    with pytest.raises(PcgGraphError):
        update(fixture, grammar_selection=descriptor)
    assert inspect(fixture) == before and not fixture[0].transactions


@pytest.mark.parametrize(
    "descriptor",
    [
        [],
        {},
        [modules()[0]] * 129,
        [{"symbol": "A", "size": 1}],
        [{"symbol": "A", "size": 1, "scalable": False, "mesh": "/Game/Mesh"}],
        [{**modules()[0], "symbol": "None"}],
        [{**modules()[0], "symbol": "A,B"}],
        [{**modules()[0], "symbol": "A" * 65}],
        [modules()[0], {**modules()[0], "symbol": "a"}],
        [{**modules()[0], "size": 0}],
        [{**modules()[0], "size": -1}],
        [{**modules()[0], "size": True}],
        [{**modules()[0], "size": float("nan")}],
        [{**modules()[0], "size": float("inf")}],
        [{**modules()[0], "size": 1_000_000_001}],
        [{**modules()[0], "size": 10**400}],
        [{**modules()[0], "scalable": 1}],
        [{**modules()[0], "debug_color": [0, 1, 0]}],
        [{**modules()[0], "debug_color": [0, 1, 2, 1]}],
        [{**modules()[0], "debug_color": [-1, 1, 0, 1]}],
        [{**modules()[0], "debug_color": [True, 1, 0, 1]}],
    ],
)
def test_bad_modules_reject_before_transaction(fixture, descriptor):
    before = inspect(fixture)
    with pytest.raises(PcgGraphError):
        update(fixture, modules_info=descriptor)
    assert inspect(fixture) == before and not fixture[0].transactions


def test_fixed_modules_require_effective_input_flag_false(fixture):
    fixture[2].properties["module_info_as_input"] = True
    with pytest.raises(PcgGraphError, match="module_info_as_input=false"):
        update(fixture, modules_info=modules())
    assert not fixture[0].transactions
    result = update(fixture, modules_info=modules(), module_info_as_input=False)
    assert values(fixture, result)["module_info_as_input"]["value"] is False


def test_switching_input_mode_cannot_implicitly_drop_edges(fixture):
    host, node, settings = fixture
    graph = host.assets["/Game/Test"]
    graph.add_edge(graph.input, "Out", node, "In")
    settings.properties["module_info_as_input"] = True
    before = inspect(fixture)
    with pytest.raises(PcgGraphError, match="Disconnect"):
        update(fixture, modules_info=modules(), module_info_as_input=False)
    assert inspect(fixture) == before and not host.transactions


def test_upper_size_boundary_and_module_count_are_authorable(fixture):
    descriptor = [{"symbol": f"Module{i}", "size": 1e9, "scalable": False} for i in range(128)]
    result = update(fixture, modules_info=descriptor)
    assert len(values(fixture, result)["modules_info"]["value"]) == 128


def test_every_property_is_prevalidated_before_any_asset_change(fixture):
    before = inspect(fixture)
    with pytest.raises(PcgGraphError):
        update(fixture, grammar_selection=literal(), modules_info=modules(), missing_field=True)
    assert inspect(fixture) == before and not fixture[0].transactions


@pytest.mark.parametrize(
    "missing", ["PCGSubdivideSplineSettings", "PCGGrammarSelection", "PCGAttributePropertyInputSelector"]
)
def test_missing_host_types_fail_closed(fixture, missing):
    setattr(fixture[0], missing, None)
    with pytest.raises(PcgGraphError):
        update(fixture, grammar_selection=literal())
    assert not fixture[0].transactions


@pytest.mark.parametrize("missing", ["PCGSubdivisionSubmodule", "Vector4"])
def test_missing_module_types_fail_closed(fixture, missing):
    setattr(fixture[0], missing, None)
    with pytest.raises(PcgGraphError):
        update(fixture, modules_info=modules())
    assert not fixture[0].transactions


def test_wrong_node_class_cannot_use_aggregate_codec(fixture):
    host, _, _ = fixture
    node = host.assets["/Game/Test"].input
    node.settings.properties["grammar_selection"] = PCGGrammarSelection()
    with pytest.raises(PcgGraphError, match="exact native PCGSubdivideSplineSettings"):
        graph_operation(host, "update_node", "/Game/Test", node_id=node.path, settings={"grammar_selection": literal()})
    assert not host.transactions


@pytest.mark.parametrize("ownership", ["external", "instance", "shared"])
def test_aggregate_edits_keep_graph_ownership_guards(fixture, ownership):
    host, node, settings = fixture
    if ownership == "external":
        settings.outer = Object("foreign")
    elif ownership == "instance":
        node.properties["settings_interface"] = Object("instance")
    else:
        host.assets["/Game/Test"].output.settings = settings
    with pytest.raises(PcgGraphError) as error:
        update(fixture, grammar_selection=literal())
    assert error.value.context["reason"] in {"settings_not_owned", "settings_shared"}
    assert not host.transactions and not settings.modifications


def test_other_aggregates_still_rejected(fixture):
    fixture[2].properties["other_struct"] = PCGGrammarSelection()
    with pytest.raises(PcgGraphError, match="unsupported"):
        update(fixture, other_struct={"anything": 3})
    assert not fixture[0].transactions


def test_native_property_and_selector_failures_precede_asset_mutation(fixture, monkeypatch):
    monkeypatch.setattr(PCGAttributePropertyInputSelector, "set_attribute_name", lambda *_: False)
    with pytest.raises(PcgGraphError, match="selector readback"):
        update(fixture, grammar_selection={"grammar_as_attribute": True, "grammar_attribute": "Grammar"})
    assert not fixture[0].transactions
    del fixture[2].properties["grammar_selection"].properties["grammar_string"]
    with pytest.raises(PcgGraphError):
        update(fixture, grammar_selection=literal())
    assert not fixture[0].transactions


@pytest.mark.parametrize("copy_fault", ["same_object", "lossy", "unavailable"])
def test_bad_copy_api_rejects_before_transaction(fixture, monkeypatch, copy_fault):
    if copy_fault == "same_object":
        monkeypatch.setattr(PCGGrammarSelection, "copy", lambda self: self)
    elif copy_fault == "lossy":

        def lossy(self):
            result = copy.deepcopy(self)
            result.properties["hidden_revision"] = 99
            return result

        monkeypatch.setattr(PCGGrammarSelection, "copy", lossy)
    else:
        monkeypatch.setattr(PCGGrammarSelection, "copy", None)
    with pytest.raises(PcgGraphError):
        update(fixture, grammar_selection=literal())
    assert not fixture[0].transactions


def test_detached_snapshots_do_not_track_native_wrapper_or_input_mutations(fixture):
    host, _, settings = fixture
    update(fixture, modules_info=modules())
    descriptor = modules()
    old, new = prepare_grammar_property(host, settings, "modules_info", descriptor, {})
    settings.properties["modules_info"][0].properties["size"] = 999
    descriptor[0]["size"] = 888
    first = old.native()
    first[0].properties["size"] = 777
    assert old.native()[0].properties["size"] == 200
    assert new.native()[0].properties["size"] == 200


def test_failure_recovers_all_struct_fields_and_nested_array_state(fixture, monkeypatch):
    host, _, settings = fixture
    update(fixture, grammar_selection=literal("A"), modules_info=modules())
    grammar = settings.properties["grammar_selection"]
    grammar.properties["hidden_revision"] = 7
    grammar.properties["grammar_attribute"].properties["extra_names"] = ["Legacy"]
    before = inspect(fixture)
    setter = settings.set_editor_property

    def fail(name, value):
        if name == "seed" and value == 99:
            settings.properties["modules_info"][0].properties["debug_color"].properties["w"] = 0.5
            raise RuntimeError("after aggregate writes")
        setter(name, value)

    monkeypatch.setattr(settings, "set_editor_property", fail)
    with pytest.raises(PcgGraphError) as error:
        update(fixture, grammar_selection=literal("B"), modules_info=[modules()[1]], seed=99)
    assert error.value.context["mutation_state"] == "restored_readback"
    assert inspect(fixture) == before and not host.saved
    assert settings.properties["grammar_selection"] is not grammar
    assert settings.properties["grammar_selection"].properties["hidden_revision"] == 7


def test_hidden_struct_difference_cannot_be_reported_as_recovered(fixture, monkeypatch):
    settings = fixture[2]
    settings.properties["grammar_selection"].properties["hidden_revision"] = 7
    setter = settings.set_editor_property

    def fail(name, value):
        if name == "seed" and value == 99:
            raise RuntimeError("fail after typed edit")
        if name == "grammar_selection" and value.properties["grammar_string"] == "":
            value.properties["hidden_revision"] = 8
        setter(name, value)

    monkeypatch.setattr(settings, "set_editor_property", fail)
    with pytest.raises(PcgGraphError) as error:
        update(fixture, grammar_selection=literal("A"), seed=99)
    assert error.value.context["mutation_state"] == "recovery_incomplete"


def test_typed_state_participates_in_inspect_and_save_fingerprint(fixture):
    before = inspect(fixture)
    update(fixture, grammar_selection=literal(), modules_info=modules())
    after = inspect(fixture)
    assert after["structural_fingerprint"] != before["structural_fingerprint"]
    assert all(item["status"] == "observed" for item in values(fixture, after).values())
    saved = graph_operation(fixture[0], "save", "/Game/Test", settings_names=["grammar_selection", "modules_info"])
    assert saved["structural_fingerprint"] == after["structural_fingerprint"]
    assert not saved["disk_reopen_verified"]


def test_export_and_native_array_limits_fail_closed(fixture, monkeypatch):
    monkeypatch.setattr(PCGGrammarSelection, "export_text", lambda self: "x" * 32769)
    with pytest.raises(PcgGraphError):
        update(fixture, grammar_selection=literal())
    fixture[2].properties["modules_info"] = [PCGSubdivisionSubmodule() for _ in range(129)]
    with pytest.raises(PcgGraphError):
        update(fixture, modules_info=modules())
    assert not fixture[0].transactions


def test_unknown_property_is_not_a_generic_codec(fixture):
    with pytest.raises(GrammarCodecError, match="Unknown grammar property"):
        prepare_grammar_property(fixture[0], fixture[2], "arbitrary_struct", {}, {})


def test_schema_and_actual_skill_dispatch(fixture, monkeypatch):
    root = Path(__file__).parents[1] / "src/dcc_mcp_unreal/skills/unreal-pcg-graph"
    definition = yaml.safe_load((root / "tools.yaml").read_text())["tools"][1]
    validator = Draft202012Validator(definition["input_schema"])
    validator.check_schema(definition["input_schema"])
    request = {
        "operation": "update_node",
        "asset_path": "/Game/Test",
        "node_id": fixture[1].path,
        "settings": {"grammar_selection": literal(), "modules_info": modules()},
    }
    validator.validate(request)
    monkeypatch.setitem(sys.modules, "unreal", fixture[0])
    from dcc_mcp_unreal.skill_runner import run_skill_script

    result = run_skill_script(str(root / "scripts/edit_pcg_graph.py"), request)
    assert result["success"] and not result["context"]["grammar_validation"]["syntax_verified"]
    for settings in (
        {"grammar_selection": {"grammar_as_attribute": False, "grammar_string": "A", "extra": 1}},
        {"modules_info": [{**modules()[0], "mesh": "/Game/Mesh"}]},
        {"unrelated_struct": {"key": 1}},
    ):
        assert list(validator.iter_errors({**request, "settings": settings}))
