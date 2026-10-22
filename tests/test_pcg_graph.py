"""Mocked contract/failure tests, not native Unreal acceptance."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from jsonschema import Draft202012Validator

from dcc_mcp_unreal.pcg_graph import PcgGraphError, graph_operation, inspect_graph


class Object:
    def __init__(self, path, **properties):
        self.path = path
        self.properties = properties
        self.modifications = 0
        self.outer = None

    def get_outer(self):
        return self.outer

    def get_path_name(self):
        return self.path

    def get_editor_property(self, name):
        if name not in self.properties:
            raise AttributeError(name)
        return self.properties[name]

    def set_editor_property(self, name, value):
        if name not in self.properties:
            raise AttributeError(name)
        self.properties[name] = value

    def modify(self):
        self.modifications += 1
        return True


class PCGSettings(Object):
    def __init__(self):
        super().__init__("settings", seed=1, enabled=True, density=0.5, label="test")

    def get_class(self):
        return Object("/Script/PCG.PCGTestSettings")


class PCGTestSettings(PCGSettings):
    pass


class Properties(Object):
    def __init__(self, label, multiple, mask):
        super().__init__("properties", label=label, allowed_types=mask)
        self.multiple = multiple

    def allows_multiple_connections(self):
        return self.multiple


class Pin(Object):
    def __init__(self, node, output, label, multiple=True, mask=2):
        super().__init__(node.path + "." + label, node=node, properties=Properties(label, multiple, mask), edges=[])
        self.output = output

    def is_output_pin(self):
        return self.output


class Node(Object):
    def __init__(self, graph, name, settings_class=PCGTestSettings):
        super().__init__(graph.path + ":" + name)
        self.graph = graph
        self.settings = settings_class()
        self.settings.outer = self
        self.properties["settings_interface"] = self.settings
        self.position = (0, 0)
        self.properties.update(input_pins=[Pin(self, False, "In")], output_pins=[Pin(self, True, "Out")])

    def get_graph(self):
        return self.graph

    def get_settings(self):
        return self.settings

    def get_node_position(self):
        return self.position

    def set_node_position(self, x, y):
        self.position = (x, y)


class PCGGraph(Object):
    def __init__(self, path):
        super().__init__(path + "." + path.rsplit("/", 1)[1], nodes=[])
        self.input = Node(self, "Input")
        self.output = Node(self, "Output")
        self.count = 0

    def get_input_node(self):
        return self.input

    def get_output_node(self):
        return self.output

    def add_node_of_type(self, cls):
        self.count += 1
        node = Node(self, f"Node{self.count}", cls)
        self.properties["nodes"].append(node)
        return node, node.settings

    def remove_node(self, node):
        self.properties["nodes"].remove(node)

    @staticmethod
    def _pins(source, source_label, target, target_label):
        output = next(
            p
            for p in source.properties["output_pins"]
            if p.properties["properties"].properties["label"] == source_label
        )
        input_pin = next(
            p for p in target.properties["input_pins"] if p.properties["properties"].properties["label"] == target_label
        )
        return output, input_pin

    def add_edge(self, source, source_label, target, target_label):
        output, input_pin = self._pins(source, source_label, target, target_label)
        edge = Object(f"{source.path}.{source_label}-{target.path}.{target_label}")
        output.properties["edges"].append(edge)
        input_pin.properties["edges"].append(edge)
        return target

    def remove_edge(self, source, source_label, target, target_label):
        output, input_pin = self._pins(source, source_label, target, target_label)
        shared = [e for e in output.properties["edges"] if e in input_pin.properties["edges"]]
        for edge in shared:
            output.properties["edges"].remove(edge)
            input_pin.properties["edges"].remove(edge)
        return bool(shared)


class Host:
    PCGGraph = PCGGraph
    PCGGraphFactory = type("PCGGraphFactory", (), {})
    PCGSettings = PCGSettings
    PCGTestSettings = PCGTestSettings
    LevelEditorSubsystem = object
    SystemLibrary = SimpleNamespace(get_engine_version=lambda: "5.5.4-test")

    def __init__(self):
        self.assets = {"/Game/Test": PCGGraph("/Game/Test")}
        self.created = []
        self.saved = []
        self.transactions = []
        self.pie = False
        self.save_result = True
        self.EditorAssetLibrary = SimpleNamespace(
            does_asset_exist=lambda p: p in self.assets,
            load_asset=lambda p: self.assets.get(p),
            save_loaded_asset=self.save,
        )
        self.AssetToolsHelpers = SimpleNamespace(get_asset_tools=lambda: SimpleNamespace(create_asset=self.create))

    def get_editor_subsystem(self, cls):
        return SimpleNamespace(is_in_play_in_editor=lambda: self.pie)

    def ScopedEditorTransaction(self, label):
        host = self

        class Transaction:
            def __enter__(self):
                host.transactions.append(("begin", label))
                return self

            def __exit__(self, *_args):
                host.transactions.append(("end", label))

        return Transaction()

    def create(self, asset_name, package_path, asset_class, factory):
        path = package_path + "/" + asset_name
        self.created.append(path)
        self.assets[path] = asset_class(path)
        return self.assets[path]

    def save(self, graph, only_if_is_dirty):
        assert only_if_is_dirty is False
        self.saved.append(graph.path)
        return self.save_result


@pytest.fixture
def host():
    return Host()


def edge_for(graph):
    return {"from_node": graph.input.path, "from_pin": "Out", "to_node": graph.output.path, "to_pin": "In"}


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/Game",
        "/Game/",
        "/Game//A",
        "/Engine/A",
        "/Game/../A",
        "/Game/A.A",
        "/Game/A B",
        "/Game/中文",
        "/Game/" + "a" * 250,
    ],
)
def test_invalid_paths_never_create(host, path):
    with pytest.raises(PcgGraphError):
        graph_operation(host, "create", path)
    assert not host.created and not host.transactions


def test_inspection_is_read_only_and_truthful(host):
    graph = host.assets["/Game/Test"]
    graph.add_edge(graph.input, "Out", graph.output, "In")
    result = graph_operation(host, "inspect", "/Game/Test", settings_names=["seed", "missing"])
    assert result["edges"] == [edge_for(graph)]
    assert result["nodes"][0]["settings"]["seed"] == {"status": "observed", "value": 1}
    assert result["nodes"][0]["settings"]["missing"] == {"status": "unavailable"}
    assert result["generation_status"] == "not_requested"
    assert not any(
        result[key] for key in ("saved", "execution_verified", "generation_verified", "disk_reopen_verified")
    )
    assert not host.created and not host.saved and not host.transactions and not graph.modifications


def test_create_no_overwrite_and_no_implicit_save(host):
    result = graph_operation(host, "create", "/Game/New")
    assert result["asset_path"] == "/Game/New.New" and not result["saved"]
    with pytest.raises(PcgGraphError, match="already exists"):
        graph_operation(host, "create", "/Game/New")
    assert host.created == ["/Game/New"] and not host.saved
    assert len(host.transactions) == 2


@pytest.mark.parametrize(
    "operation,arguments", [("create", {}), ("add_node", {"settings_class": "PCGTestSettings"}), ("save", {})]
)
def test_pie_rejects_mutations(host, operation, arguments):
    host.pie = True
    with pytest.raises(PcgGraphError, match="Play In Editor"):
        graph_operation(host, operation, "/Game/Test", **arguments)
    assert not host.transactions and not host.created and not host.saved


def test_missing_capability_and_wrong_asset_fail_closed(host):
    host.PCGGraph = None
    with pytest.raises(PcgGraphError, match="unavailable"):
        graph_operation(host, "inspect", "/Game/Test")
    host.PCGGraph = PCGGraph
    host.assets["/Game/Test"] = Object("wrong")
    with pytest.raises(PcgGraphError, match="not a PCGGraph"):
        graph_operation(host, "inspect", "/Game/Test")


def test_add_and_update_node(host):
    added = graph_operation(host, "add_node", "/Game/Test", settings_class="PCGTestSettings", position=[12, -4])
    identity = added["created_node_id"]
    result = graph_operation(
        host, "update_node", "/Game/Test", node_id=identity, position=[9, 3], settings={"seed": 42}
    )
    row = next(n for n in result["nodes"] if n["node_id"] == identity)
    assert row["position"] == [9, 3] and row["settings"]["seed"]["value"] == 42
    assert not host.saved and len(host.transactions) == 4


@pytest.mark.parametrize(
    "settings",
    [
        {"unknown": 3},
        {"seed": True},
        {"enabled": 1},
        {"density": float("nan")},
        {"density": float("inf")},
        {"label": "x" * 4097},
        {"Seed": 2},
    ],
)
def test_bad_settings_leave_graph_untouched(host, settings):
    graph = host.assets["/Game/Test"]
    before = inspect_graph(graph, ["seed"])
    with pytest.raises(PcgGraphError):
        graph_operation(host, "update_node", "/Game/Test", node_id=graph.input.path, settings=settings)
    assert inspect_graph(graph, ["seed"]) == before and not host.transactions


@pytest.mark.parametrize("position", [[True, 2], [1.0, 2], [2**31, 0], [0], "12"])
def test_bad_position_leaves_graph_untouched(host, position):
    with pytest.raises(PcgGraphError):
        graph_operation(host, "add_node", "/Game/Test", settings_class="PCGTestSettings", position=position)
    assert not host.transactions


def test_node_creation_failure_restores_topology(host, monkeypatch):
    graph = host.assets["/Game/Test"]
    original = graph.add_node_of_type

    def fail(cls):
        original(cls)
        raise RuntimeError("injected post-create failure")

    monkeypatch.setattr(graph, "add_node_of_type", fail)
    with pytest.raises(PcgGraphError) as error:
        graph_operation(host, "add_node", "/Game/Test", settings_class="PCGTestSettings")
    assert error.value.context["mutation_state"] == "restored_readback"
    assert not error.value.context["dirty_state_restored"]
    assert not graph.properties["nodes"] and not host.saved


def test_incomplete_rollback_is_reported(host, monkeypatch):
    graph = host.assets["/Game/Test"]
    original = graph.add_node_of_type
    monkeypatch.setattr(graph, "add_node_of_type", lambda cls: (original(cls), "wrong", "signature"))
    monkeypatch.setattr(graph, "remove_node", lambda node: (_ for _ in ()).throw(RuntimeError("rollback blocked")))
    with pytest.raises(PcgGraphError) as error:
        graph_operation(host, "add_node", "/Game/Test", settings_class="PCGTestSettings")
    assert error.value.context["mutation_state"] == "recovery_incomplete"
    assert error.value.context["recovery_errors"] == ["rollback blocked"]


def test_settings_write_failure_restores_prior_values(host, monkeypatch):
    graph = host.assets["/Game/Test"]
    settings = graph.input.settings
    original = settings.set_editor_property

    def setter(name, value):
        if name == "density" and value == 0.7:
            raise RuntimeError("injected write failure")
        original(name, value)

    monkeypatch.setattr(settings, "set_editor_property", setter)
    with pytest.raises(PcgGraphError) as error:
        graph_operation(
            host, "update_node", "/Game/Test", node_id=graph.input.path, settings={"seed": 10, "density": 0.7}
        )
    assert error.value.context["mutation_state"] == "restored_readback"
    assert settings.properties["seed"] == 1 and settings.properties["density"] == 0.5


def test_connect_disconnect_and_duplicate_are_observed(host):
    graph = host.assets["/Game/Test"]
    edge = edge_for(graph)
    assert graph_operation(host, "connect", "/Game/Test", edge=edge)["edges"] == [edge]
    assert not graph_operation(host, "connect", "/Game/Test", edge=edge)["changed"]
    assert graph_operation(host, "disconnect", "/Game/Test", edge=edge)["edges"] == []
    assert not graph_operation(host, "disconnect", "/Game/Test", edge=edge)["changed"]
    assert len(host.transactions) == 4


@pytest.mark.parametrize(
    "fault", ["cross_graph", "wrong_direction", "incompatible", "cardinality", "self", "extra_key"]
)
def test_bad_connections_do_not_mutate(host, fault):
    graph = host.assets["/Game/Test"]
    edge = edge_for(graph)
    if fault == "cross_graph":
        edge["to_node"] = PCGGraph("/Game/Other").output.path
    elif fault == "wrong_direction":
        edge["to_pin"] = "Out"
    elif fault == "incompatible":
        graph.output.properties["input_pins"][0].properties["properties"].properties["allowed_types"] = 4
    elif fault == "cardinality":
        node, _ = graph.add_node_of_type(PCGTestSettings)
        graph.add_edge(node, "Out", graph.output, "In")
        graph.output.properties["input_pins"][0].properties["properties"].multiple = False
    elif fault == "self":
        edge["to_node"] = graph.input.path
    else:
        edge["unexpected"] = "x"
    before = inspect_graph(graph)
    with pytest.raises(PcgGraphError):
        graph_operation(host, "connect", "/Game/Test", edge=edge)
    assert inspect_graph(graph) == before and not host.transactions


def test_partial_edge_write_reports_incomplete_recovery(host, monkeypatch):
    graph = host.assets["/Game/Test"]

    def partial(*args):
        graph.input.properties["output_pins"][0].properties["edges"].append(Object("partial"))
        raise RuntimeError("partial edge")

    monkeypatch.setattr(graph, "add_edge", partial)
    with pytest.raises(PcgGraphError) as error:
        graph_operation(host, "connect", "/Game/Test", edge=edge_for(graph))
    assert error.value.context["mutation_state"] == "recovery_incomplete"
    assert error.value.context["recovery_errors"]


def test_save_return_does_not_claim_disk_reopen(host):
    result = graph_operation(host, "save", "/Game/Test")
    assert result["saved"] and result["save_returned_success"]
    assert not result["disk_reopen_verified"] and not result["generation_verified"]
    assert "cache" in result["readback_source"]


@pytest.mark.parametrize("result", [False, None])
def test_failed_save_keeps_asset_and_reports_uncertainty(host, result):
    host.save_result = result
    with pytest.raises(PcgGraphError) as error:
        graph_operation(host, "save", "/Game/Test")
    assert error.value.context["save_outcome"] == "unverified"
    assert not error.value.context["automatic_deletion_attempted"]
    assert "/Game/Test" in host.assets


def test_save_readback_mismatch_is_not_success(host):
    def changed(graph, **kwargs):
        graph.input.position = (1, 2)
        return True

    host.EditorAssetLibrary.save_loaded_asset = changed
    with pytest.raises(PcgGraphError, match="differs"):
        graph_operation(host, "save", "/Game/Test")


def test_bound_rejects_instead_of_truncating(host):
    graph = host.assets["/Game/Test"]
    graph.properties["nodes"] = [Node(graph, f"N{i}") for i in range(255)]
    with pytest.raises(PcgGraphError, match="inspection limit"):
        graph_operation(host, "inspect", "/Game/Test")
    with pytest.raises(PcgGraphError):
        graph_operation(host, "add_node", "/Game/Test", settings_class="PCGTestSettings")
    assert not host.transactions


def test_duplicate_and_cross_owned_nodes_are_rejected(host):
    graph = host.assets["/Game/Test"]
    graph.properties["nodes"] = [Node(PCGGraph("/Game/Other"), "foreign")]
    with pytest.raises(PcgGraphError, match="another graph"):
        inspect_graph(graph)
    node = Node(graph, "Duplicate")
    graph.properties["nodes"] = [node, node]
    with pytest.raises(PcgGraphError, match="duplicate"):
        inspect_graph(graph)


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("create", {"settings": {}}),
        ("add_node", {"settings_class": "PCGTestSettings", "settings": {"seed": 3}}),
        ("inspect", {"edge": {}}),
        ("remove_node", {}),
    ],
)
def test_unused_arguments_and_unimplemented_operations_are_rejected(host, operation, arguments):
    with pytest.raises(PcgGraphError):
        graph_operation(host, operation, "/Game/New", **arguments)
    assert not host.created and not host.transactions


def test_skill_schema_examples_and_entrypoint(host, monkeypatch):
    root = Path(__file__).parents[1] / "src/dcc_mcp_unreal/skills/unreal-pcg-graph"
    definitions = yaml.safe_load((root / "tools.yaml").read_text())["tools"]
    for tool in definitions:
        Draft202012Validator.check_schema(tool["input_schema"])
        validator = Draft202012Validator(tool["input_schema"])
        for example in tool["call_examples"]:
            validator.validate(example["arguments"])
        assert tool["affinity"] == "main" and tool["enforce_thread_affinity"]
    monkeypatch.setitem(sys.modules, "unreal", host)
    from dcc_mcp_unreal.skill_runner import run_skill_script

    result = run_skill_script(str(root / "scripts/inspect_pcg_graph.py"), {"asset_path": "/Game/Test"})
    assert result["success"]
    result = run_skill_script(
        str(root / "scripts/edit_pcg_graph.py"), {"operation": "create", "asset_path": "/Game/Test"}
    )
    assert not result["success"]
    assert result["context"]["reason"] == "overwrite_refused"


def test_unknown_pie_state_is_not_permission_to_edit(host):
    host.pie = None
    with pytest.raises(PcgGraphError) as error:
        graph_operation(host, "create", "/Game/New")
    assert error.value.context["reason"] == "unknown_editor_state"
    assert not host.created


def test_redirected_asset_identity_cannot_be_edited(host):
    host.assets["/Game/Test"] = PCGGraph("/Game/Elsewhere")
    with pytest.raises(PcgGraphError, match="redirects"):
        graph_operation(host, "save", "/Game/Test")
    assert not host.saved


def test_created_wrong_identity_is_retained_with_explicit_recovery(host):
    host.AssetToolsHelpers = SimpleNamespace(
        get_asset_tools=lambda: SimpleNamespace(create_asset=lambda **kwargs: PCGGraph("/Game/Elsewhere"))
    )
    with pytest.raises(PcgGraphError) as error:
        graph_operation(host, "create", "/Game/New")
    assert error.value.context["mutation_state"] == "creation_outcome_requires_inspection"
    assert not error.value.context["automatic_deletion_attempted"]


def test_total_output_limit_rejects_instead_of_truncating(host):
    graph = host.assets["/Game/Test"]
    for _ in range(150):
        node, _ = graph.add_node_of_type(PCGTestSettings)
        for name in ("one", "two"):
            node.settings.properties[name] = "a" * 4096
    with pytest.raises(PcgGraphError, match="1 MiB"):
        inspect_graph(graph, ["one", "two"])


def test_pin_direction_and_endpoint_integrity_are_checked(host):
    graph = host.assets["/Game/Test"]
    graph.input.properties["output_pins"][0].output = False
    with pytest.raises(PcgGraphError, match="direction"):
        inspect_graph(graph)


def test_unknown_engine_version_does_not_claim_feature_support(host):
    host.SystemLibrary = None
    result = graph_operation(host, "inspect", "/Game/Test")
    assert result["engine"] == {"version": None, "used_as_feature_gate": False}
    assert not result["execution_verified"]


def test_missing_transaction_api_prevents_mutation(host):
    host.ScopedEditorTransaction = None
    with pytest.raises(PcgGraphError, match="unavailable"):
        graph_operation(host, "add_node", "/Game/Test", settings_class="PCGTestSettings")
    assert not host.assets["/Game/Test"].properties["nodes"]


@pytest.mark.parametrize("field,value", [("to_node", "/Game/Foreign:Node"), ("to_pin", "Missing")])
def test_disconnected_noop_still_validates_node_and_pin(host, field, value):
    edge = edge_for(host.assets["/Game/Test"])
    edge[field] = value
    with pytest.raises(PcgGraphError):
        graph_operation(host, "disconnect", "/Game/Test", edge=edge)
    assert not host.transactions


@pytest.mark.parametrize("field", ["direction", "cardinality"])
def test_unknown_pin_metadata_fails_closed(host, field):
    graph = host.assets["/Game/Test"]
    pin = graph.input.properties["input_pins"][0]
    if field == "direction":
        pin.output = None
    else:
        pin.properties["properties"].multiple = None
    with pytest.raises(PcgGraphError):
        graph_operation(host, "connect", "/Game/Test", edge=edge_for(graph))
    assert not host.transactions


def test_empty_engine_query_is_unknown(host):
    host.SystemLibrary = SimpleNamespace(get_engine_version=lambda: None)
    assert graph_operation(host, "inspect", "/Game/Test")["engine"]["version"] is None


@pytest.mark.parametrize("ownership", ["external_graph", "instance", "shared_node", "unknown_outer"])
def test_settings_updates_cannot_mutate_external_instanced_or_shared_settings(host, ownership):
    graph = host.assets["/Game/Test"]
    node = graph.input
    if ownership == "external_graph":
        node.settings = PCGGraph("/Game/External").input.settings
        node.properties["settings_interface"] = node.settings
    elif ownership == "instance":
        node.properties["settings_interface"] = Object("SettingsInstance")
    elif ownership == "shared_node":
        graph.output.settings = node.settings
    else:
        node.settings.outer = None
    before_seed = node.settings.properties["seed"]
    with pytest.raises(PcgGraphError) as error:
        graph_operation(host, "update_node", "/Game/Test", node_id=node.path, settings={"seed": 20})
    assert error.value.context["reason"] in {"settings_not_owned", "settings_shared"}
    assert node.settings.properties["seed"] == before_seed
    assert not host.transactions and node.settings.modifications == 0


def test_position_only_edit_does_not_mutate_external_settings(host):
    graph = host.assets["/Game/Test"]
    external = PCGGraph("/Game/External").input.settings
    graph.input.settings = external
    graph.input.properties["settings_interface"] = Object("SettingsInstance")
    result = graph_operation(host, "update_node", "/Game/Test", node_id=graph.input.path, position=[50, -20])
    assert next(row for row in result["nodes"] if row["node_id"] == graph.input.path)["position"] == [50, -20]
    assert external.properties["seed"] == 1 and external.modifications == 0
