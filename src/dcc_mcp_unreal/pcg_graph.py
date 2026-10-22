"""Bounded PCG graph authoring using documented, runtime-gated Python APIs.

No Unreal import at module scope. Structural readback is not engine compilation,
fresh generation, or proof of persistence across an editor restart.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Callable

_MAX_NODES = 256
_MAX_PINS = 64
_MAX_EDGES = 4096
_MAX_OUTPUT_BYTES = 1024 * 1024
_PATH = re.compile(r"/Game/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\Z")


class PcgGraphError(RuntimeError):
    """A rejected operation or a failure with explicit recovery evidence."""

    def __init__(self, message: str, **context: Any):
        super().__init__(message)
        self.context = context


def _method(owner: Any, name: str) -> Callable:
    method = getattr(owner, name, None)
    if not callable(method):
        raise PcgGraphError(f"Required API {name} is unavailable on this host", reason="unsupported_api")
    return method


def _property(owner: Any, name: str) -> Any:
    try:
        return _method(owner, "get_editor_property")(name)
    except PcgGraphError:
        raise
    except Exception as exc:
        raise PcgGraphError(f"Cannot read reflected property {name}: {exc}", reason="unsupported_property") from exc


def _identity(obj: Any) -> str:
    value = _method(obj, "get_path_name")()
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise PcgGraphError("Object did not expose a bounded persistent path")
    return value


def _bounded(values: Any, limit: int, label: str) -> list:
    if len(values) > limit:
        raise PcgGraphError(f"{label} exceeds inspection limit {limit}", reason="inspection_limit")
    return list(values)


def _path(value: str) -> str:
    if not isinstance(value, str) or len(value) > 240 or not _PATH.fullmatch(value):
        raise PcgGraphError("Use a /Game/Folder/Asset package path with ASCII letters, numbers or underscores")
    return value


def _position(value: Any) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise PcgGraphError("position must contain two int32 coordinates")
    if any(type(item) is not int or not -(2**31) <= item < 2**31 for item in value):
        raise PcgGraphError("position must contain two int32 coordinates")
    return tuple(value)


def _nodes(graph: Any) -> list:
    nodes = _bounded(_property(graph, "nodes"), _MAX_NODES - 2, "Graph node count")
    for name in ("get_input_node", "get_output_node"):
        node = _method(graph, name)()
        if node is not None and node not in nodes:
            nodes.append(node)
    identities = set()
    for node in nodes:
        identity = _identity(node)
        if identity in identities or _method(node, "get_graph")() != graph:
            raise PcgGraphError("Graph has duplicate node identities or a node owned by another graph")
        identities.add(identity)
    return nodes


def _node(graph: Any, node_id: str) -> Any:
    for node in _nodes(graph):
        if _identity(node) == node_id:
            return node
    raise PcgGraphError("node_id is not an observed node in this graph", reason="node_not_owned")


def inspect_graph(graph: Any, settings_names: list | None = None) -> dict:
    """Inspect complete bounded topology, identifying edges through shared pins.

    PCGEdge endpoint fields are not part of the documented Python surface. Read
    shared edge identities from PCGPin.edges rather than guessing those fields.
    """
    names = [] if settings_names is None else settings_names
    if (
        not isinstance(names, list)
        or len(names) > 32
        or any(not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", name) for name in names)
    ):
        raise PcgGraphError("settings_names must contain at most 32 reflected property names")
    nodes = []
    endpoints: dict[str, list] = {}
    edge_references = 0
    for node in _nodes(graph):
        node_id = _identity(node)
        settings = _method(node, "get_settings")()
        row = {
            "node_id": node_id,
            "settings_class": _identity(_method(settings, "get_class")()) if settings is not None else None,
            "position": list(_position(_method(node, "get_node_position")())),
            "pins": [],
            "settings": {},
        }
        for name in names:
            try:
                value = _property(settings, name)
                if type(value) not in (bool, int, float, str) or (type(value) is float and not math.isfinite(value)):
                    row["settings"][name] = {"status": "unsupported_value_type"}
                elif isinstance(value, str) and len(value) > 4096:
                    row["settings"][name] = {"status": "value_exceeds_limit"}
                else:
                    row["settings"][name] = {"status": "observed", "value": value}
            except PcgGraphError:
                row["settings"][name] = {"status": "unavailable"}
        for direction, property_name in (("input", "input_pins"), ("output", "output_pins")):
            labels = set()
            for pin in _bounded(_property(node, property_name), _MAX_PINS, "Node pin count"):
                output_state = _method(pin, "is_output_pin")()
                if (
                    type(output_state) is not bool
                    or _property(pin, "node") != node
                    or output_state != (direction == "output")
                ):
                    raise PcgGraphError("Pin ownership or direction is inconsistent")
                properties = _property(pin, "properties")
                label = str(_property(properties, "label"))
                if label in labels or len(label) > 256:
                    raise PcgGraphError("Pin labels are duplicated or exceed the inspection limit")
                labels.add(label)
                allowed_types = int(_property(properties, "allowed_types"))
                multiple = _method(properties, "allows_multiple_connections")()
                if type(multiple) is not bool:
                    raise PcgGraphError("Pin connection cardinality is unknown")
                edges = _bounded(_property(pin, "edges"), _MAX_EDGES, "Pin edge count")
                row["pins"].append(
                    {
                        "label": label,
                        "direction": direction,
                        "allowed_types": allowed_types,
                        "allow_multiple_connections": multiple,
                        "edge_count": len(edges),
                    }
                )
                for edge in edges:
                    edge_references += 1
                    if edge_references > 2 * _MAX_EDGES:
                        raise PcgGraphError("Graph exceeds edge-reference limit", reason="inspection_limit")
                    edge_id = _identity(edge)
                    endpoints.setdefault(edge_id, []).append((direction, node_id, label))
                    if len(endpoints) > _MAX_EDGES:
                        raise PcgGraphError("Graph exceeds edge inspection limit", reason="inspection_limit")
        nodes.append(row)
    edges = []
    for pair in endpoints.values():
        source = [item for item in pair if item[0] == "output"]
        target = [item for item in pair if item[0] == "input"]
        if len(pair) != 2 or len(source) != 1 or len(target) != 1:
            raise PcgGraphError("Edge does not have exactly one owned input and output endpoint")
        edges.append(
            {"from_node": source[0][1], "from_pin": source[0][2], "to_node": target[0][1], "to_pin": target[0][2]}
        )
    data = {
        "asset_path": _identity(graph),
        "nodes": sorted(nodes, key=lambda row: row["node_id"]),
        "edges": sorted(edges, key=lambda row: tuple(row.values())),
    }
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    if len(serialized) > _MAX_OUTPUT_BYTES:
        raise PcgGraphError("Graph readback exceeds 1 MiB output limit", reason="inspection_limit")
    digest = hashlib.sha256(serialized).hexdigest()
    return {
        **data,
        "structural_fingerprint": digest,
        "validation_scope": "bounded structural readback only",
        "engine_compile_verified": False,
        "disk_reopen_verified": False,
        "generation_verified": False,
    }


def _engine(unreal: Any) -> dict:
    try:
        value = _method(getattr(unreal, "SystemLibrary", None), "get_engine_version")()
        return {"version": value[:256] if isinstance(value, str) and value else None, "used_as_feature_gate": False}
    except Exception:
        return {"version": None, "used_as_feature_gate": False}


def _load(unreal: Any, path: str) -> Any:
    graph_class = getattr(unreal, "PCGGraph", None)
    if not isinstance(graph_class, type):
        raise PcgGraphError("unreal.PCGGraph is unavailable", reason="unsupported_api")
    graph = _method(getattr(unreal, "EditorAssetLibrary", None), "load_asset")(path)
    if not isinstance(graph, graph_class):
        raise PcgGraphError("Asset does not exist or is not a PCGGraph", asset_path=path)
    if _identity(graph) != path + "." + path.rsplit("/", 1)[1]:
        raise PcgGraphError("Loaded graph identity differs from the explicit path; redirects are not edited")
    return graph


def _editor(unreal: Any) -> None:
    # Do not infer PIE state from whether an editor world also exists.
    subsystem_class = getattr(unreal, "LevelEditorSubsystem", None)
    if subsystem_class is None:
        raise PcgGraphError("LevelEditorSubsystem is unavailable", reason="unsupported_api")
    subsystem = _method(unreal, "get_editor_subsystem")(subsystem_class)
    state = _method(subsystem, "is_in_play_in_editor")()
    if type(state) is not bool:
        raise PcgGraphError("PIE state query returned an unknown result", reason="unknown_editor_state")
    if state:
        raise PcgGraphError("Stop Play In Editor before graph authoring", reason="pie_active")


def _mutate(
    unreal: Any,
    graph: Any,
    action: Callable,
    rollback: Callable,
    verify: Callable,
    settings_names: list | None = None,
    objects: tuple = (),
) -> dict:
    transaction = _method(unreal, "ScopedEditorTransaction")
    before = inspect_graph(graph, settings_names)
    # Check rollback/transaction requirements before touching any object.
    modifiers = [_method(obj, "modify") for obj in (graph, *objects)]
    with transaction("DCC-MCP PCG graph edit"):
        try:
            for modify in modifiers:
                if modify() is False:
                    raise PcgGraphError("Object declined transaction recording")
            action()
            verify()
            return inspect_graph(graph, settings_names)
        except Exception as exc:
            recovery_errors = []
            try:
                rollback()
            except Exception as recovery_exc:
                recovery_errors.append(str(recovery_exc)[:500])
            try:
                restored = (
                    inspect_graph(graph, settings_names)["structural_fingerprint"] == before["structural_fingerprint"]
                )
            except Exception as recovery_exc:
                restored = False
                recovery_errors.append(str(recovery_exc)[:500])
            raise PcgGraphError(
                str(exc)[:1000],
                mutation_state="restored_readback" if restored else "recovery_incomplete",
                recovery_errors=recovery_errors,
                saved=False,
                dirty_state_restored=False,
            ) from exc


def _pin(graph: Any, node_id: str, label: str, direction: str) -> tuple:
    node = _node(graph, node_id)
    pins = _bounded(_property(node, f"{direction}_pins"), _MAX_PINS, "Node pin count")
    matches = [pin for pin in pins if str(_property(_property(pin, "properties"), "label")) == label]
    if len(matches) != 1:
        raise PcgGraphError("Pin label is missing or ambiguous for the requested direction")
    return node, matches[0]


def _edit_edge(unreal: Any, graph: Any, operation: str, edge: dict) -> dict:
    expected = {"from_node", "from_pin", "to_node", "to_pin"}
    if (
        not isinstance(edge, dict)
        or set(edge) != expected
        or any(not isinstance(v, str) or not v for v in edge.values())
    ):
        raise PcgGraphError("edge requires exact from_node, from_pin, to_node and to_pin strings")
    before = inspect_graph(graph)
    exists = edge in before["edges"]
    source, output = _pin(graph, edge["from_node"], edge["from_pin"], "output")
    target, input_pin = _pin(graph, edge["to_node"], edge["to_pin"], "input")
    if exists == (operation == "connect"):
        return {**before, "changed": False}
    add, remove = _method(graph, "add_edge"), _method(graph, "remove_edge")
    args = (source, edge["from_pin"], target, edge["to_pin"])
    if operation == "connect":
        if source == target:
            raise PcgGraphError("Self connections are not supported")
        output_properties, input_properties = _property(output, "properties"), _property(input_pin, "properties")
        if not int(_property(output_properties, "allowed_types")) & int(_property(input_properties, "allowed_types")):
            raise PcgGraphError("Pin data-type masks do not overlap")
        for pin, properties in ((output, output_properties), (input_pin, input_properties)):
            if len(_property(pin, "edges")) and not _method(properties, "allows_multiple_connections")():
                raise PcgGraphError("Pin cardinality would replace an existing connection")

    def verify():
        after = inspect_graph(graph)
        expected_edges = (
            before["edges"] + [edge] if operation == "connect" else [e for e in before["edges"] if e != edge]
        )
        if sorted(after["edges"], key=str) != sorted(expected_edges, key=str):
            raise PcgGraphError("Engine edge readback differs from the requested topology")

    def restore():
        present = edge in inspect_graph(graph)["edges"]
        if present != exists:
            (add if exists else remove)(*args)

    result = _mutate(
        unreal,
        graph,
        lambda: (add if operation == "connect" else remove)(*args),
        restore,
        verify,
        objects=(source, target, output, input_pin),
    )
    return {**result, "changed": True}


def _update(unreal: Any, graph: Any, node_id: str, position: Any, settings: Any) -> dict:
    node = _node(graph, node_id)
    if settings is None:
        settings = {}
    if not isinstance(settings, dict) or len(settings) > 32:
        raise PcgGraphError("settings must be an object with at most 32 scalar properties")
    names = list(settings)
    inspect_graph(graph, names)  # validate names before reading/writing anything
    native_settings = _method(node, "get_settings")()
    if settings:
        if _property(node, "settings_interface") != native_settings or _method(native_settings, "get_outer")() != node:
            raise PcgGraphError(
                "Scalar edits require direct settings owned by this node; external or instanced settings are not edited",
                reason="settings_not_owned",
            )
        if any(other != node and _method(other, "get_settings")() == native_settings for other in _nodes(graph)):
            raise PcgGraphError("Settings are shared by another node in this graph", reason="settings_shared")
    old = {}
    for name, value in settings.items():
        current = _property(native_settings, name)
        if type(current) not in (bool, int, float, str) or type(value) is not type(current):
            raise PcgGraphError(
                f"{name} requires the exact reflected scalar type; enums/objects/structs are unsupported"
            )
        if (type(value) is float and not math.isfinite(value)) or (type(value) is str and len(value) > 4096):
            raise PcgGraphError(f"{name} is nonfinite or exceeds the scalar size limit")
        old[name] = current
    original_position = _position(_method(node, "get_node_position")())
    target_position = original_position if position is None else _position(position)
    set_position = _method(node, "set_node_position")
    set_property = _method(native_settings, "set_editor_property") if settings else None

    def apply(values, coordinates):
        for name, value in values.items():
            set_property(name, value)
        set_position(*coordinates)

    def verify():
        if _position(node.get_node_position()) != target_position or any(
            _property(native_settings, key) != value for key, value in settings.items()
        ):
            raise PcgGraphError("Node readback differs from the requested values")

    return _mutate(
        unreal,
        graph,
        lambda: apply(settings, target_position),
        lambda: apply(old, original_position),
        verify,
        names,
        (node, native_settings) if settings else (node,),
    )


def graph_operation(
    unreal: Any,
    operation: str,
    asset_path: str,
    *,
    node_id: str = "",
    settings_class: str = "",
    position: Any = None,
    settings: dict | None = None,
    edge: dict | None = None,
    settings_names: list | None = None,
) -> dict:
    """Perform one explicit operation; edits never save or generate implicitly."""
    path = _path(asset_path)
    if not isinstance(operation, str) or operation not in {
        "inspect",
        "create",
        "add_node",
        "update_node",
        "connect",
        "disconnect",
        "save",
    }:
        raise PcgGraphError("Unsupported operation; node removal and generation are not implemented in this slice")
    allowed = {
        "inspect": {"settings_names"},
        "create": set(),
        "add_node": {"settings_class", "position"},
        "update_node": {"node_id", "position", "settings"},
        "connect": {"edge"},
        "disconnect": {"edge"},
        "save": {"settings_names"},
    }
    supplied = {
        name
        for name, value in {
            "node_id": node_id or None,
            "settings_class": settings_class or None,
            "position": position,
            "settings": settings,
            "edge": edge,
            "settings_names": settings_names,
        }.items()
        if value is not None
    }
    if supplied - allowed[operation]:
        raise PcgGraphError(f"Arguments are not applicable to {operation}: {sorted(supplied - allowed[operation])}")
    if operation != "inspect":
        _editor(unreal)
    if operation == "create":
        library = getattr(unreal, "EditorAssetLibrary", None)
        if _method(library, "does_asset_exist")(path):
            raise PcgGraphError("Asset already exists; replacement is never implicit", reason="overwrite_refused")
        graph_class, factory_class = getattr(unreal, "PCGGraph", None), getattr(unreal, "PCGGraphFactory", None)
        if not isinstance(graph_class, type) or not isinstance(factory_class, type):
            raise PcgGraphError("PCGGraph and PCGGraphFactory must be available", reason="unsupported_api")
        create = _method(_method(getattr(unreal, "AssetToolsHelpers", None), "get_asset_tools")(), "create_asset")
        transaction = _method(unreal, "ScopedEditorTransaction")
        graph = None
        try:
            with transaction("DCC-MCP create PCG graph"):
                folder, name = path.rsplit("/", 1)
                graph = create(asset_name=name, package_path=folder, asset_class=graph_class, factory=factory_class())
                if not isinstance(graph, graph_class):
                    raise PcgGraphError("Asset factory did not return a PCGGraph")
                if _identity(graph) != path + "." + name:
                    raise PcgGraphError("Created graph identity differs from the explicit asset path")
                result = inspect_graph(graph)
        except Exception as exc:
            raise PcgGraphError(
                str(exc)[:1000],
                asset_path=path,
                mutation_state="creation_outcome_requires_inspection",
                saved=False,
                automatic_deletion_attempted=False,
            ) from exc
    else:
        graph = _load(unreal, path)
        if operation == "inspect":
            result = inspect_graph(graph, settings_names)
        elif operation in {"connect", "disconnect"}:
            result = _edit_edge(unreal, graph, operation, edge)
        elif operation == "update_node":
            result = _update(unreal, graph, node_id, position, settings)
        elif operation == "add_node":
            if not isinstance(settings_class, str) or not re.fullmatch(r"PCG[A-Za-z0-9_]+Settings", settings_class):
                raise PcgGraphError("settings_class must name an exposed PCG settings class")
            cls, base = getattr(unreal, settings_class, None), getattr(unreal, "PCGSettings", None)
            if not isinstance(cls, type) or not isinstance(base, type) or not issubclass(cls, base):
                raise PcgGraphError("Requested settings class is not an available PCGSettings subclass")
            coordinates = (0, 0) if position is None else _position(position)
            add, remove = _method(graph, "add_node_of_type"), _method(graph, "remove_node")
            before_ids = {_identity(node) for node in _nodes(graph)}
            if len(before_ids) >= _MAX_NODES:
                raise PcgGraphError("Graph node inspection limit reached")
            created = []

            def add_node():
                returned = add(cls)
                if not isinstance(returned, tuple) or len(returned) != 2:
                    raise PcgGraphError("Unexpected add_node_of_type return signature")
                node, native_settings = returned
                if _identity(node) in before_ids or _method(node, "get_graph")() != graph:
                    raise PcgGraphError("New node ownership/identity is invalid")
                if not isinstance(native_settings, cls) or _method(node, "get_settings")() != native_settings:
                    raise PcgGraphError("New node settings do not match the requested native class")
                created.append(_identity(node))
                _method(node, "set_node_position")(*coordinates)

            def restore_nodes():
                # Include nodes created before an exception or unexpected return.
                for node in _nodes(graph):
                    if _identity(node) not in before_ids:
                        remove(node)

            def verify_node():
                if {_identity(node) for node in _nodes(graph)} != before_ids | set(created) or len(created) != 1:
                    raise PcgGraphError("Node creation readback mismatch")
                if _position(_node(graph, created[0]).get_node_position()) != coordinates:
                    raise PcgGraphError("Node position readback mismatch")

            result = _mutate(unreal, graph, add_node, restore_nodes, verify_node)
            result["created_node_id"] = created[0]
        else:
            before = inspect_graph(graph, settings_names)
            save = _method(getattr(unreal, "EditorAssetLibrary", None), "save_loaded_asset")
            try:
                if save(graph, only_if_is_dirty=False) is not True:
                    raise PcgGraphError("Engine did not confirm save success")
                result = inspect_graph(_load(unreal, path), settings_names)
                if result["structural_fingerprint"] != before["structural_fingerprint"]:
                    raise PcgGraphError("Save/readback topology differs; inspect the asset before retrying")
            except Exception as exc:
                raise PcgGraphError(
                    str(exc)[:1000],
                    asset_path=path,
                    save_outcome="unverified",
                    disk_reopen_verified=False,
                    automatic_deletion_attempted=False,
                ) from exc
            result["save_returned_success"] = True
            result["readback_source"] = "current editor object cache; not a disk reopen"
    return {
        **result,
        "operation": operation,
        "engine": _engine(unreal),
        "saved": operation == "save",
        "generation_status": "not_requested",
        "execution_verified": False,
    }
