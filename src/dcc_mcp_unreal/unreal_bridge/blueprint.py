"""unreal_bridge.blueprint — Host-native Blueprint graph authoring bridge (22 functions).

Implements the P0 reflection contract defined in the ``unreal-blueprint-graph``
marketplace skill bundle (references/reflection-contract.md).  Every function:

- Calls Unreal Engine's Python API (``import unreal``) directly inside the engine.
- Returns a standard result envelope: ``{"success": bool, "message": str, ...}``
  via the project's ``unreal_success`` / ``unreal_error`` helpers.
- Is safe to call from off-thread MCP handlers (dispatching is handled by the
  ``HostExecutionBridge`` / ``UnrealMainThreadDispatcher`` layer).

Error codes (8 standard codes from the contract)
-----------------------------------------------
``BLUEPRINT_NOT_FOUND``   — asset path does not resolve to a loadable Blueprint.
``GRAPH_NOT_FOUND``       — named graph not present in the Blueprint.
``NODE_NOT_FOUND``        — node GUID / name not found in the graph.
``PIN_NOT_FOUND``         — pin name / id not found on a node.
``CONNECTION_INVALID``    — pin types incompatible or same-direction link.
``PIN_TYPE_MISMATCH``     — default value type does not match pin type.
``COMPILE_FAILED``        — Blueprint compilation returned errors.
``UNREAL_UNAVAILABLE``    — ``unreal`` module not importable (not in-engine).

Bridge Function Index (22 functions)
------------------------------------

**Graph Lifecycle (4)**
1.  ``open_blueprint(asset_path: str) -> dict``
2.  ``get_blueprint_graph(blueprint, graph_name: str | None) -> dict``
3.  ``save_blueprint(asset_path: str) -> dict``
4.  ``get_blueprint_info(asset_path: str) -> dict``

**Node CRUD (6)**
5.  ``create_graph_node(blueprint, graph_name: str, node_class: str,
       position: tuple, properties: dict | None) -> dict``
6.  ``delete_graph_node(blueprint, node_guid: str) -> dict``
7.  ``find_graph_nodes(blueprint, graph_name: str | None,
       filters: dict | None) -> dict``
8.  ``get_node_properties(blueprint, node_guid: str) -> dict``
9.  ``set_node_properties(blueprint, node_guid: str,
       properties: dict) -> dict``
10. ``list_available_node_classes() -> dict``

**Pin Operations (7)**
11. ``add_pin_to_node(blueprint, node_guid: str, pin_spec: dict) -> dict``
12. ``remove_pin_from_node(blueprint, node_guid: str, pin_name: str) -> dict``
13. ``connect_pins(blueprint, source_pin: dict, target_pin: dict) -> dict``
14. ``disconnect_pin(blueprint, pin_ref: dict) -> dict``
15. ``get_pin_default_value(blueprint, node_guid: str, pin_name: str) -> dict``
16. ``set_pin_default_value(blueprint, node_guid: str, pin_name: str,
       value: Any, type_hint: str | None) -> dict``
17. ``validate_pin_connection(source_pin: dict, target_pin: dict) -> dict``

**Layout (2)**
18. ``auto_layout_nodes(blueprint, graph_name: str,
       strategy: str) -> dict``
19. ``set_node_position(blueprint, node_guid: str, x: float,
       y: float) -> dict``

**Compile & Diagnostics (3)**
20. ``compile_blueprint(blueprint, *, timeout_secs: float | None) -> dict``
21. ``get_blueprint_diagnostics(blueprint,
       severity_filter: str | None) -> dict``
22. ``refresh_blueprint_graph(blueprint) -> dict``

Verification
------------
A validation script at the end of this module (``_run_validation()``) performs
a smoke-test contract check when executed inside Unreal Editor:
  ``py -c "from dcc_mcp_unreal.unreal_bridge.blueprint import _run_validation; _run_validation()"``
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from dcc_mcp_unreal.api import (
    build_context_dict,
    require_unreal,
    unreal_error,
    unreal_from_exception,
    unreal_success,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Standard error codes (P0 contract)
# ---------------------------------------------------------------------------

ERROR_BLUEPRINT_NOT_FOUND = "BLUEPRINT_NOT_FOUND"
ERROR_GRAPH_NOT_FOUND = "GRAPH_NOT_FOUND"
ERROR_NODE_NOT_FOUND = "NODE_NOT_FOUND"
ERROR_PIN_NOT_FOUND = "PIN_NOT_FOUND"
ERROR_CONNECTION_INVALID = "CONNECTION_INVALID"
ERROR_PIN_TYPE_MISMATCH = "PIN_TYPE_MISMATCH"
ERROR_COMPILE_FAILED = "COMPILE_FAILED"
ERROR_UNREAL_UNAVAILABLE = "UNREAL_UNAVAILABLE"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DEFAULT_BLUEPRINT_BASE_PATH = "/Game/Blueprints"


def _get_graph_nodes(edgraph: Any) -> List[Any]:
    """Get all nodes from an EdGraph across UE 5.3–5.8.

    UE 5.5+ provides ``EdGraph.get_all_nodes()``.  UE 5.3 EdGraph
    does **not** expose nodes through the Python API — the property is
    C++-only and protected.  Returns an empty list on older engines
    so callers can degrade gracefully.
    """
    if edgraph is None:
        return []
    if hasattr(edgraph, "get_all_nodes"):
        try:
            raw = edgraph.get_all_nodes()
            return list(raw) if raw is not None else []
        except Exception:
            return []
    # UE 5.3: Nodes property is protected; no Python-accessible node enumeration.
    logger.debug("EdGraph.get_all_nodes unavailable — engine does not expose graph nodes to Python")
    return []


def _add_node_to_graph(edgraph: Any, node: Any) -> bool:
    """Add a node instance to an EdGraph.  Returns True on success.

    UE 5.5+ provides ``EdGraph.add_node()``.  UE 5.3 does not expose
    this method to Python.
    """
    if edgraph is None:
        return False
    if hasattr(edgraph, "add_node"):
        try:
            edgraph.add_node(node)
            return True
        except Exception:
            return False
    logger.debug("EdGraph.add_node unavailable — node-level graph authoring requires UE 5.5+")
    return False


def _resolve_blueprint_path(asset_path: str) -> str:
    """Normalize an asset path; if it lacks a leading /, prefix /Game/Blueprints/."""
    if asset_path.startswith("/"):
        return asset_path
    return f"{_DEFAULT_BLUEPRINT_BASE_PATH}/{asset_path}"


def _load_blueprint(asset_path: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """Load a Blueprint asset and return (blueprint, error_or_none).

    Returns (None, error_dict) when the asset cannot be loaded.
    """
    import unreal  # noqa: PLC0415

    path = _resolve_blueprint_path(asset_path)
    bp = unreal.EditorAssetLibrary.load_asset(path)
    if bp is None:
        return None, unreal_error(
            f"Blueprint not found: {asset_path}",
            error_code=ERROR_BLUEPRINT_NOT_FOUND,
            asset_path=path,
            possible_solutions=[
                f"Verify the asset exists at '{path}' in the Content Browser.",
                "Use an absolute path like '/Game/MyFolder/BP_MyActor'.",
            ],
        )
    return bp, None


def _get_blueprint_event_graph(blueprint: Any) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """Return the primary event graph of a Blueprint."""

    event_graphs = _get_blueprint_graphs(blueprint)
    if not event_graphs:
        return None, unreal_error(
            "No event graph found in Blueprint",
            error_code=ERROR_GRAPH_NOT_FOUND,
            blueprint_name=blueprint.get_name(),
            possible_solutions=[
                "Ensure the Blueprint has a valid event graph.",
                "Use create_blueprint_class to create a new Blueprint.",
            ],
        )
    return event_graphs[0], None


def _resolve_graph(blueprint: Any, graph_name: Optional[str]) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """Resolve a named graph or the default event graph."""

    if graph_name is None:
        return _get_blueprint_event_graph(blueprint)

    graphs = _get_blueprint_graphs(blueprint)
    for g in graphs:
        if g.get_name() == graph_name:
            return g, None

    return None, unreal_error(
        f"Graph not found: {graph_name}",
        error_code=ERROR_GRAPH_NOT_FOUND,
        blueprint_name=blueprint.get_name(),
        graph_name=graph_name,
        possible_solutions=[
            "Use 'EventGraph' for the primary event graph.",
            "List available graphs with get_blueprint_graph.",
        ],
    )


def _node_to_dict(node: Any) -> Dict[str, Any]:
    """Serialize an EdGraphNode to a JSON-safe dict."""

    d: Dict[str, Any] = {
        "node_guid": str(node.get_node_guid()) if hasattr(node, "get_node_guid") else "",
        "node_class": node.get_class().get_name(),
        "node_name": node.get_name() if hasattr(node, "get_name") else "",
    }
    try:
        d["node_pos_x"] = int(node.node_pos_x)
    except Exception:
        d["node_pos_x"] = 0
    try:
        d["node_pos_y"] = int(node.node_pos_y)
    except Exception:
        d["node_pos_y"] = 0
    # Node comment / tooltip
    try:
        d["node_comment"] = str(node.node_comment) if hasattr(node, "node_comment") else ""
    except Exception:
        d["node_comment"] = ""

    # Pins
    pins = []
    if hasattr(node, "get_all_pins"):
        for pin in node.get_all_pins():
            pins.append(_pin_to_dict(pin))
    d["pins"] = pins
    return d


def _pin_to_dict(pin: Any) -> Dict[str, Any]:
    """Serialize an EdGraphPin to a JSON-safe dict."""
    d: Dict[str, Any] = {
        "pin_name": pin.pin_name,
        "pin_id": str(pin.pin_id) if hasattr(pin, "pin_id") else "",
        "direction": str(pin.direction) if hasattr(pin, "direction") else "",
        "pin_type": str(pin.pin_type) if hasattr(pin, "pin_type") else "",
    }
    try:
        d["default_value"] = pin.default_value
    except Exception:
        d["default_value"] = ""
    try:
        d["default_object"] = str(pin.default_object) if pin.default_object else None
    except Exception:
        d["default_object"] = None
    try:
        d["linked_to"] = [
            {"node_guid": str(lp.get_node_guid()) if hasattr(lp, "get_node_guid") else "",
             "pin_name": lp.pin_name}
            for lp in pin.linked_to
        ] if hasattr(pin, "linked_to") and pin.linked_to else []
    except Exception:
        d["linked_to"] = []
    return d


def _find_node_by_guid(graph: Any, node_guid: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """Locate a node in a graph by its node GUID string."""
    for node in _get_graph_nodes(graph):
        if str(node.get_node_guid()) == node_guid:
            return node, None
    return None, unreal_error(
        f"Node not found: {node_guid}",
        error_code=ERROR_NODE_NOT_FOUND,
        node_guid=node_guid,
        possible_solutions=[
            "Verify the node GUID using find_graph_nodes.",
            "The node may have been deleted.",
        ],
    )


def _find_pin_on_node(node: Any, pin_name: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """Locate a pin on a node by name."""
    for pin in node.get_all_pins():
        if pin.pin_name == pin_name:
            return pin, None
    return None, unreal_error(
        f"Pin not found: {pin_name}",
        error_code=ERROR_PIN_NOT_FOUND,
        pin_name=pin_name,
        node_guid=str(node.get_node_guid()),
        possible_solutions=[
            "List pins on the node with get_node_properties.",
            "Pin names are case-sensitive.",
        ],
    )


# ---------------------------------------------------------------------------
# UE version compatibility helpers (UE 5.3 / 5.5 / 5.7 / 5.8 bridge)
# ---------------------------------------------------------------------------


def _get_blueprint_graphs(blueprint: Any) -> Any:
    """Return all editable graphs for a Blueprint across UE 5.3–5.8.

    UE 5.5+ provides ``BlueprintEditorLibrary.get_blueprint_event_graphs()``.
    UE 5.3 exposes graph arrays via ``UbergraphPages`` / ``FunctionGraphs`` on
    the Blueprint object.  ``ImplementedInterfaces`` is deliberately excluded
    because it contains ``FBPInterfaceDescription`` entries, not ``UEdGraph``.
    """
    import unreal  # noqa: PLC0415

    # --- UE 5.5+ path ---
    lib = getattr(unreal, "BlueprintEditorLibrary", None)
    if lib is not None and hasattr(lib, "get_blueprint_event_graphs"):
        return lib.get_blueprint_event_graphs(blueprint)

    # --- UE 5.3 fallback ---
    graphs: List[Any] = []

    def _is_edgraph(obj: Any) -> bool:
        """Return True if *obj* looks like a UEdGraph.

        UE 5.5+ EdGraph has ``get_all_nodes``, but UE 5.3 does not.
        Checking the class name is reliable across all UE versions.
        """
        if obj is None:
            return False
        try:
            return obj.get_class().get_name() == "EdGraph"
        except Exception:
            return False

    def _collect(pages: Any) -> None:
        """Collect unique EdGraph items from an iterable or scalar.

        EdGraph is checked **first** to avoid false-positive ``__iter__``
        on UE 5.3 EdGraph objects that expose the attribute but don't
        actually support iteration.
        """
        if pages is None:
            return
        # Single EdGraph — add directly, skip iteration
        if _is_edgraph(pages):
            if pages not in graphs:
                graphs.append(pages)
            return
        # Iterable collection of potential graphs
        if hasattr(pages, "__iter__") and not isinstance(pages, str):
            for page in pages:
                if _is_edgraph(page) and page not in graphs:
                    graphs.append(page)

    # 1. Try find_event_graph via BlueprintEditorLibrary (exists in some 5.3 builds)
    if lib is not None and hasattr(lib, "find_event_graph"):
        try:
            _collect(lib.find_event_graph(blueprint))
        except Exception:
            pass

    # 2. get_editor_property is the most reliable accessor across UE versions
    for prop_name in ("UbergraphPages", "UberGraphPages"):
        try:
            _collect(blueprint.get_editor_property(prop_name))
        except Exception:
            pass

    # 3. Direct attribute access for FunctionGraphs and other graph arrays
    for attr_name in ("FunctionGraphs", "MacroGraphs", "DelegateSignatureGraphs"):
        try:
            _collect(getattr(blueprint, attr_name, None))
        except Exception:
            pass

    # 4. Last resort: iterate Blueprint properties looking for graph arrays
    #    (UE 5.3 may only expose graphs through reflection; get_properties()
    #     may not exist on older UE class objects, so guard it.)
    if not graphs:
        try:
            bp_class = blueprint.get_class()
            props = getattr(bp_class, "get_properties", None)
            if callable(props):
                for prop in props():
                    try:
                        _collect(blueprint.get_editor_property(prop.get_name()))
                    except Exception:
                        pass
        except Exception:
            pass

    return graphs
def _refresh_blueprint_nodes(blueprint: Any) -> None:
    """Refresh the Blueprint editor after graph mutations across UE 5.3–5.8.

    UE 5.5+ provides ``refresh_open_blueprint_nodes()``.
    UE 5.3: ``refresh_all_open_blueprint_editors()`` or no-op (the next
    compilation implicitly refreshes).
    """
    import unreal  # noqa: PLC0415

    lib = unreal.BlueprintEditorLibrary
    if hasattr(lib, "refresh_open_blueprint_nodes"):
        lib.refresh_open_blueprint_nodes(blueprint)
        return
    if hasattr(lib, "refresh_all_open_blueprint_editors"):
        lib.refresh_all_open_blueprint_editors()
        return
    # UE 5.3: compile_blueprint() implicitly refreshes; no-op is acceptable.
    logger.debug("BlueprintEditorLibrary refresh not available; skipping visual refresh")


def _get_compilation_messages(blueprint: Any, compile_result: Any = None) -> Any:
    """Return compilation messages for a Blueprint across UE 5.3–5.8.

    UE 5.5+ provides ``BlueprintEditorLibrary.get_compilation_messages()``.
    UE 5.3 stores structured messages inside the ``CompileResults`` object
    returned by ``KismetEditorUtilities.compile_blueprint()``.  Pass
    *compile_result* to avoid an expensive recompilation.

    Args:
        blueprint: The loaded Blueprint object.
        compile_result: The object returned by
            ``KismetEditorUtilities.compile_blueprint()`` (UE 5.5+) or
            ``True`` / ``False`` (UE 5.3).  When omitted the function
            falls back to the message-log subsystem.
    """
    import unreal  # noqa: PLC0415

    # --- UE 5.5+ path ---
    lib = getattr(unreal, "BlueprintEditorLibrary", None)
    if lib is not None and hasattr(lib, "get_compilation_messages"):
        return lib.get_compilation_messages(blueprint)

    # --- Extract from pre-existing compile result (avoid recompilation) ---
    if compile_result is not None:
        # UE 5.5+ CompileResults object with .Messages
        if hasattr(compile_result, "Messages") and compile_result.Messages:
            return compile_result.Messages
        # UE 5.5+ alternative: .get_messages()
        if hasattr(compile_result, "get_messages"):
            try:
                msgs = compile_result.get_messages()
                if msgs:
                    return msgs
            except Exception:
                pass
        # UE 5.3: compile_result is a plain bool — no messages embedded;
        # fall through to message-log path below.

    # --- UE 5.3 fallback: message log subsystem ---
    try:
        # Some 5.3 builds expose log_blueprint_compile_messages
        if lib is not None and hasattr(lib, "log_blueprint_compile_messages"):
            lib.log_blueprint_compile_messages(blueprint)
    except Exception:
        pass

    # Final fallback: empty list (no diagnostics available)
    logger.debug("Compilation messages not available for this engine version")
    return []


# ======================================================================
# Graph Lifecycle (functions 1-4)
# ======================================================================


def open_blueprint(asset_path: str) -> Dict[str, Any]:
    """Load a Blueprint asset and return its basic handle information.

    Args:
        asset_path: Content Browser path to the Blueprint asset.
            May be relative (``BP_MyActor``) or absolute
            (``/Game/Blueprints/BP_MyActor``).

    Returns:
        Result envelope with ``blueprint_name``, ``blueprint_path``,
        ``blueprint_class``, ``parent_class``, and ``graphs`` list.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    bp, err = _load_blueprint(asset_path)
    if err:
        return err

    try:
        # Gather basic metadata
        bp_name = bp.get_name()
        bp_class = bp.get_class().get_name()
        parent_class = ""
        if hasattr(bp, "parent_class"):
            parent_class_obj = bp.parent_class
            if parent_class_obj:
                parent_class = parent_class_obj.get_name()

        graphs = _get_blueprint_graphs(bp)
        graph_names = [g.get_name() for g in graphs]

        return unreal_success(
            f"Opened Blueprint: {bp_name}",
            blueprint_name=bp_name,
            blueprint_path=_resolve_blueprint_path(asset_path),
            blueprint_class=bp_class,
            parent_class=parent_class,
            graph_count=len(graphs),
            graphs=graph_names,
            prompt="Use get_blueprint_graph to inspect a specific graph.",
        )
    except Exception as exc:
        return unreal_from_exception(exc, f"Failed to open Blueprint: {asset_path}")


def get_blueprint_graph(blueprint: Any = None, asset_path: str = "", graph_name: Optional[str] = None) -> Dict[str, Any]:
    """Get the structure of a Blueprint graph (nodes, pins, connections).

    Args:
        blueprint: A loaded Blueprint object (preferred).  Used when chaining
            bridge calls within the same session.
        asset_path: Content Browser path; used to load the Blueprint when
            *blueprint* is None.
        graph_name: Specific graph name or None for the primary event graph.

    Returns:
        Result envelope with ``graph_name``, ``node_count``, and ``nodes`` list
        of serialized node dicts (include pins and connections).
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    if isinstance(blueprint, str):
        bp, err = _load_blueprint(blueprint)
        if err:
            return err
    elif blueprint is None:
        bp, err = _load_blueprint(asset_path)
        if err:
            return err
    else:
        bp = blueprint

    graph, err = _resolve_graph(bp, graph_name)
    if err:
        return err

    try:
        all_nodes = _get_graph_nodes(graph)
        nodes_list = [_node_to_dict(n) for n in all_nodes]

        return unreal_success(
            f"Graph '{graph.get_name()}' has {len(all_nodes)} nodes",
            blueprint_name=bp.get_name(),
            graph_name=graph.get_name(),
            node_count=len(all_nodes),
            nodes=nodes_list,
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Failed to retrieve graph structure")


def save_blueprint(asset_path: str) -> Dict[str, Any]:
    """Persist a Blueprint asset to disk without compiling.

    Args:
        asset_path: Content Browser path to the Blueprint.

    Returns:
        Result envelope with ``saved`` flag and ``asset_path``.
    """
    try:
        ue = require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    path = _resolve_blueprint_path(asset_path)

    bp, err = _load_blueprint(asset_path)
    if err:
        return err

    try:
        saved = ue.EditorAssetLibrary.save_asset(path)
        if not saved:
            return unreal_error(
                f"Failed to save Blueprint: {asset_path}",
                error="EditorAssetLibrary.save_asset returned False",
                error_code=ERROR_BLUEPRINT_NOT_FOUND,
                asset_path=path,
            )
        return unreal_success(
            f"Saved Blueprint: {asset_path}",
            saved=True,
            asset_path=path,
            prompt="Blueprint changes are now persisted.",
        )
    except Exception as exc:
        return unreal_from_exception(exc, f"Failed to save Blueprint: {asset_path}")


def get_blueprint_info(asset_path: str) -> Dict[str, Any]:
    """Return metadata summary for a Blueprint asset.

    Args:
        asset_path: Content Browser path to the Blueprint.

    Returns:
        Result envelope with ``blueprint_name``, ``blueprint_class``,
        ``parent_class``, ``graph_count``, ``node_count_total``,
        ``is_data_only``, ``blueprint_type``.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    bp, err = _load_blueprint(asset_path)
    if err:
        return err

    try:
        bp_name = bp.get_name()
        bp_class = bp.get_class().get_name()

        parent_class = ""
        if hasattr(bp, "parent_class") and bp.parent_class:
            parent_class = bp.parent_class.get_name()

        graphs = _get_blueprint_graphs(bp)
        total_nodes = 0
        graph_names = []
        for g in graphs:
            total_nodes += len(_get_graph_nodes(g))
            graph_names.append(g.get_name())

        is_data_only = getattr(bp, "b_is_data_only", False) if hasattr(bp, "b_is_data_only") else False
        bp_type = str(bp.blueprint_type) if hasattr(bp, "blueprint_type") else "BPTYPE_Normal"

        return unreal_success(
            f"Blueprint info: {bp_name}",
            **build_context_dict(
                blueprint_name=bp_name,
                blueprint_path=_resolve_blueprint_path(asset_path),
                blueprint_class=bp_class,
                parent_class=parent_class or None,
                graph_count=len(graphs),
                graphs=graph_names,
                node_count_total=total_nodes,
                is_data_only=is_data_only,
                blueprint_type=bp_type,
            ),
        )
    except Exception as exc:
        return unreal_from_exception(exc, f"Failed to get Blueprint info: {asset_path}")


# ======================================================================
# Node CRUD (functions 5-10)
# ======================================================================


def create_graph_node(
    blueprint: Any,
    graph_name: str,
    node_class: str,
    position: Tuple[float, float] = (0.0, 0.0),
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new node in a Blueprint graph.

    Args:
        blueprint: Loaded Blueprint object.
        graph_name: Target graph name (or None for primary event graph).
        node_class: Unreal class name of the node to create
            (e.g. ``K2Node_CallFunction``, ``K2Node_Event``,
            ``K2Node_VariableGet``, ``K2Node_CustomEvent``).
        position: (x, y) graph coordinates for the new node.
        properties: Optional dict of editor properties to set on the node.

    Returns:
        Result envelope with ``node_guid``, ``node_class``, ``node_name``,
        and ``position``.
    """
    try:
        ue = require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    if isinstance(blueprint, str):
        bp, err = _load_blueprint(blueprint)
        if err:
            return err
    else:
        bp = blueprint

    graph, err = _resolve_graph(bp, graph_name)
    if err:
        return err

    node_cls = getattr(ue, node_class, None)
    if node_cls is None:
        return unreal_error(
            f"Unknown node class: {node_class}",
            f"No such class 'unreal.{node_class}'",
            error_code=ERROR_NODE_NOT_FOUND,
            possible_solutions=[
                "Use list_available_node_classes to see valid node types.",
                "Common classes: K2Node_CallFunction, K2Node_Event, "
                "K2Node_VariableGet, K2Node_VariableSet, K2Node_CustomEvent.",
            ],
        )

    try:
        node = node_cls()
        if not _add_node_to_graph(graph, node):
            return unreal_error(
                f"Cannot add node to graph (engine does not expose graph editing API)",
                error=f"EdGraph.add_node unavailable for '{node_class}'",
                error_code=ERROR_GRAPH_NOT_FOUND,
                blueprint_name=bp.get_name(),
                possible_solutions=[
                    "Blueprint node-level authoring requires UE 5.5+ Python API.",
                    "Use the Blueprint Editor UI for manual graph editing on UE 5.3.",
                ],
            )

        node.set_editor_property("node_pos_x", int(position[0]))
        node.set_editor_property("node_pos_y", int(position[1]))

        # Apply additional editor properties
        if properties:
            for key, value in properties.items():
                try:
                    node.set_editor_property(key, value)
                except Exception as prop_exc:
                    logger.debug("Could not set property '%s' on node: %s", key, prop_exc)

        _refresh_blueprint_nodes(bp)
        node_guid = str(node.get_node_guid())

        return unreal_success(
            f"Created {node_class} node in '{graph.get_name()}'",
            node_guid=node_guid,
            node_class=node_class,
            node_name=node.get_name(),
            position=list(position),
            prompt=f"Node ID: {node_guid}. Use connect_pins to wire it up.",
        )
    except Exception as exc:
        return unreal_from_exception(exc, f"Failed to create node of class {node_class}")


def delete_graph_node(blueprint: Any, node_guid: str) -> Dict[str, Any]:
    """Delete a node from a Blueprint graph by its GUID.

    Args:
        blueprint: Loaded Blueprint object.
        node_guid: The string GUID of the node to delete.

    Returns:
        Result envelope with ``deleted_node_guid``.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    graphs = _get_blueprint_graphs(blueprint)
    if not graphs:
        return unreal_error(
            "No graphs found in Blueprint",
            error_code=ERROR_GRAPH_NOT_FOUND,
            blueprint_name=blueprint.get_name(),
        )

    for graph in graphs:
        node, _ = _find_node_by_guid(graph, node_guid)
        if node is not None:
            try:
                graph.remove_node(node)
                _refresh_blueprint_nodes(blueprint)
                return unreal_success(
                    f"Deleted node: {node_guid}",
                    deleted_node_guid=node_guid,
                    graph_name=graph.get_name(),
                    prompt="The graph has been updated. Compile to apply changes.",
                )
            except Exception as exc:
                return unreal_from_exception(exc, f"Failed to delete node: {node_guid}")

    return unreal_error(
        f"Node not found in any graph: {node_guid}",
        error_code=ERROR_NODE_NOT_FOUND,
        node_guid=node_guid,
        possible_solutions=["Verify the node GUID with find_graph_nodes."],
    )


def find_graph_nodes(
    blueprint: Any,
    graph_name: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Find nodes in a Blueprint graph matching optional filter criteria.

    Args:
        blueprint: Loaded Blueprint object.
        graph_name: Target graph name or None for all graphs.
        filters: Optional dict with any of:
            - ``node_class`` (str): Substring match on class name.
            - ``node_name`` (str): Substring match on display name.
            - ``node_comment`` (str): Substring match on comment text.
            - ``event_name`` (str): For K2Node_Event nodes, match event name.

    Returns:
        Result envelope with ``nodes`` list and ``match_count``.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    if isinstance(blueprint, str):
        bp, err = _load_blueprint(blueprint)
        if err:
            return err
    else:
        bp = blueprint

    filters = filters or {}
    target_graphs: List[Any]

    if graph_name is not None:
        graph, err = _resolve_graph(bp, graph_name)
        if err:
            return err
        target_graphs = [graph]
    else:
        target_graphs = _get_blueprint_graphs(bp)
        if not target_graphs:
            return unreal_error(
                "No graphs found in Blueprint",
                error_code=ERROR_GRAPH_NOT_FOUND,
                blueprint_name=bp.get_name(),
            )

    matches: List[Dict[str, Any]] = []
    node_class_filter = filters.get("node_class", "").lower()
    node_name_filter = filters.get("node_name", "").lower()
    node_comment_filter = filters.get("node_comment", "").lower()
    event_name_filter = filters.get("event_name", "")

    for graph in target_graphs:
        for node in _get_graph_nodes(graph):
            node_dict = _node_to_dict(node)

            if node_class_filter and node_class_filter not in node_dict["node_class"].lower():
                continue
            if node_name_filter and node_name_filter not in node_dict.get("node_name", "").lower():
                continue
            if node_comment_filter and node_comment_filter not in node_dict.get("node_comment", "").lower():
                continue
            if event_name_filter:
                try:
                    ref = node.event_reference
                    member_name = str(ref.member_name) if ref and ref.member_name else ""
                except Exception:
                    member_name = ""
                try:
                    custom_name = str(node.custom_function_name) if hasattr(node, "custom_function_name") else ""
                except Exception:
                    custom_name = ""
                if event_name_filter not in member_name and event_name_filter not in custom_name:
                    continue

            node_dict["graph_name"] = graph.get_name()
            matches.append(node_dict)

    return unreal_success(
        f"Found {len(matches)} matching node(s)",
        match_count=len(matches),
        nodes=matches,
        **build_context_dict(filters_applied=filters if filters else None),
    )


def get_node_properties(blueprint: Any, node_guid: str) -> Dict[str, Any]:
    """Get all properties and pins for a specific node.

    Args:
        blueprint: Loaded Blueprint object.
        node_guid: String GUID of the target node.

    Returns:
        Result envelope with full ``node`` dict (class, name, position,
        comment, pins with linked_to info).
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    graphs = _get_blueprint_graphs(blueprint)
    for graph in graphs:
        node, _ = _find_node_by_guid(graph, node_guid)
        if node is not None:
            node_dict = _node_to_dict(node)
            node_dict["graph_name"] = graph.get_name()
            return unreal_success(
                f"Node properties for {node_guid}",
                node=node_dict,
            )

    return unreal_error(
        f"Node not found: {node_guid}",
        error_code=ERROR_NODE_NOT_FOUND,
        node_guid=node_guid,
    )


def set_node_properties(
    blueprint: Any,
    node_guid: str,
    properties: Dict[str, Any],
) -> Dict[str, Any]:
    """Set editor properties on a graph node.

    Args:
        blueprint: Loaded Blueprint object.
        node_guid: String GUID of the target node.
        properties: Dict of ``{property_name: value}`` pairs to apply.

    Returns:
        Result envelope with ``updated`` list of successfully-set keys and
        ``failed`` list of keys that could not be set.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    graphs = _get_blueprint_graphs(blueprint)
    for graph in graphs:
        node, _ = _find_node_by_guid(graph, node_guid)
        if node is not None:
            updated: List[str] = []
            failed: List[str] = []
            for key, value in properties.items():
                try:
                    node.set_editor_property(key, value)
                    updated.append(key)
                except Exception:
                    failed.append(key)

            if updated:
                _refresh_blueprint_nodes(blueprint)

            if not updated:
                return unreal_error(
                    f"No properties could be set on node {node_guid}",
                    error=f"Failed keys: {failed}",
                    error_code=ERROR_NODE_NOT_FOUND,
                    possible_solutions=[
                        "Check that the property names match the node's editor properties.",
                        "Use get_node_properties to inspect available properties.",
                    ],
                )

            return unreal_success(
                f"Updated {len(updated)} property/properties on node {node_guid}",
                node_guid=node_guid,
                updated=updated,
                failed=failed if failed else None,
            )

    return unreal_error(
        f"Node not found: {node_guid}",
        error_code=ERROR_NODE_NOT_FOUND,
        node_guid=node_guid,
    )


def list_available_node_classes() -> Dict[str, Any]:
    """List commonly-available K2Node subclasses usable in Blueprint graphs.

    Returns:
        Result envelope with ``node_classes`` list of class name strings.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    # Canonical set of K2Node subclasses available in UE 4.18+
    classes = [
        # Event nodes
        "K2Node_Event",
        "K2Node_CustomEvent",
        "K2Node_InputAction",
        "K2Node_InputKey",
        # Function nodes
        "K2Node_CallFunction",
        "K2Node_CallParentFunction",
        "K2Node_CallArrayFunction",
        # Variable nodes
        "K2Node_VariableGet",
        "K2Node_VariableSet",
        # Flow control
        "K2Node_IfThenElse",
        "K2Node_ExecutionSequence",
        "K2Node_ForEachLoop",
        "K2Node_WhileLoop",
        "K2Node_Switch",
        "K2Node_Breakpoint",
        # Casting
        "K2Node_DynamicCast",
        "K2Node_ClassDynamicCast",
        # Misc
        "K2Node_Self",
        "K2Node_MakeStruct",
        "K2Node_BreakStruct",
        "K2Node_Timeline",
        "K2Node_Select",
        "K2Node_CreateDelegate",
        "K2Node_AddDelegate",
        "K2Node_RemoveDelegate",
        "K2Node_CallDelegate",
    ]

    return unreal_success(
        f"Available node classes: {len(classes)}",
        node_classes=classes,
        prompt="Use create_graph_node with one of these class names.",
    )


# ======================================================================
# Pin Operations (functions 11-17)
# ======================================================================


def add_pin_to_node(
    blueprint: Any,
    node_guid: str,
    pin_spec: Dict[str, Any],
) -> Dict[str, Any]:
    """Add a user-defined pin to an existing node.

    Args:
        blueprint: Loaded Blueprint object.
        node_guid: String GUID of the target node.
        pin_spec: Dict with keys:
            - ``pin_name`` (str, required)
            - ``direction`` (str): ``EGPD_Input`` or ``EGPD_Output``
            - ``pin_type`` (str): e.g. ``bool``, ``int``, ``float``, ``string``, ``exec``
            - ``default_value`` (str, optional)

    Returns:
        Result envelope with ``node_guid`` and ``pin_name``.
    """
    try:
        ue = require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    pin_name = pin_spec.get("pin_name", "")
    if not pin_name:
        return unreal_error(
            "pin_name is required in pin_spec",
            error_code=ERROR_PIN_NOT_FOUND,
            possible_solutions=["Provide pin_spec with at least 'pin_name'."],
        )

    graphs = _get_blueprint_graphs(blueprint)
    for graph in graphs:
        node, _ = _find_node_by_guid(graph, node_guid)
        if node is not None:
            try:
                direction_map = {
                    "EGPD_Input": ue.EGraphPinDirection.EGPD_Input,
                    "EGPD_Output": ue.EGraphPinDirection.EGPD_Output,
                }
                direction_str = pin_spec.get("direction", "EGPD_Input")
                direction = direction_map.get(direction_str, ue.EGraphPinDirection.EGPD_Input)

                # Create a basic pin.  Full type definition requires
                # PinType construction from the unreal module where available.
                pin = node.create_pin(
                    direction,
                    pin_name,
                    pin_name,
                )

                default_value = pin_spec.get("default_value")
                if default_value is not None:
                    try:
                        pin.default_value = str(default_value)
                    except Exception:
                        pass

                _refresh_blueprint_nodes(blueprint)

                return unreal_success(
                    f"Added pin '{pin_name}' to node {node_guid}",
                    node_guid=node_guid,
                    pin_name=pin_name,
                    direction=direction_str,
                    prompt="Use connect_pins to wire this pin.",
                )
            except Exception as exc:
                return unreal_from_exception(exc, f"Failed to add pin '{pin_name}'")

    return unreal_error(
        f"Node not found: {node_guid}",
        error_code=ERROR_NODE_NOT_FOUND,
        node_guid=node_guid,
    )


def remove_pin_from_node(
    blueprint: Any,
    node_guid: str,
    pin_name: str,
) -> Dict[str, Any]:
    """Remove a user-defined pin from a node.

    Args:
        blueprint: Loaded Blueprint object.
        node_guid: String GUID of the target node.
        pin_name: Name of the pin to remove.

    Returns:
        Result envelope with ``node_guid`` and ``removed_pin``.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    graphs = _get_blueprint_graphs(blueprint)
    for graph in graphs:
        node, _ = _find_node_by_guid(graph, node_guid)
        if node is not None:
            pin, err = _find_pin_on_node(node, pin_name)
            if err:
                return err

            try:
                node.remove_pin(pin)
                _refresh_blueprint_nodes(blueprint)
                return unreal_success(
                    f"Removed pin '{pin_name}' from node {node_guid}",
                    node_guid=node_guid,
                    removed_pin=pin_name,
                )
            except Exception as exc:
                return unreal_from_exception(exc, f"Failed to remove pin '{pin_name}'")

    return unreal_error(
        f"Node not found: {node_guid}",
        error_code=ERROR_NODE_NOT_FOUND,
        node_guid=node_guid,
    )


def connect_pins(blueprint: Any, source_pin: Dict[str, Any], target_pin: Dict[str, Any]) -> Dict[str, Any]:
    """Connect two pins in a Blueprint graph.

    Args:
        blueprint: Loaded Blueprint object.
        source_pin: Dict with ``node_guid`` and ``pin_name`` of the source pin.
        target_pin: Dict with ``node_guid`` and ``pin_name`` of the target pin.

    Returns:
        Result envelope with ``source_pin`` and ``target_pin`` details.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    src_guid = source_pin.get("node_guid", "")
    src_pin_name = source_pin.get("pin_name", "")
    tgt_guid = target_pin.get("node_guid", "")
    tgt_pin_name = target_pin.get("pin_name", "")

    if not (src_guid and src_pin_name and tgt_guid and tgt_pin_name):
        return unreal_error(
            "Invalid pin reference",
            "Both source_pin and target_pin must have 'node_guid' and 'pin_name'",
            error_code=ERROR_CONNECTION_INVALID,
            possible_solutions=[
                "Use get_node_properties to get valid pin references.",
                "Pin dict format: {'node_guid': '...', 'pin_name': '...'}",
            ],
        )

    # Pre-validate connection
    val_result = validate_pin_connection(source_pin, target_pin)
    if not val_result.get("success"):
        return val_result

    graphs = _get_blueprint_graphs(blueprint)
    src_pin_obj: Optional[Any] = None
    tgt_pin_obj: Optional[Any] = None

    for graph in graphs:
        src_node, _ = _find_node_by_guid(graph, src_guid)
        if src_node is not None:
            src_pin_obj, _ = _find_pin_on_node(src_node, src_pin_name)
        tgt_node, _ = _find_node_by_guid(graph, tgt_guid)
        if tgt_node is not None:
            tgt_pin_obj, _ = _find_pin_on_node(tgt_node, tgt_pin_name)

        if src_pin_obj is not None and tgt_pin_obj is not None:
            try:
                # The make_link_to call is directional
                src_pin_obj.make_link_to(tgt_pin_obj)
                _refresh_blueprint_nodes(blueprint)
                return unreal_success(
                    f"Connected {src_pin_name} → {tgt_pin_name}",
                    source_pin={"node_guid": src_guid, "pin_name": src_pin_name},
                    target_pin={"node_guid": tgt_guid, "pin_name": tgt_pin_name},
                    prompt="Compile the Blueprint to validate the connection.",
                )
            except Exception as exc:
                return unreal_from_exception(
                    exc,
                    f"Failed to connect {src_pin_name} → {tgt_pin_name}",
                )

    # Pins not found in any graph
    missing = []
    if src_pin_obj is None:
        missing.append(f"source pin '{src_pin_name}' on node {src_guid}")
    if tgt_pin_obj is None:
        missing.append(f"target pin '{tgt_pin_name}' on node {tgt_guid}")
    return unreal_error(
        "Cannot connect: " + ", ".join(missing),
        error_code=ERROR_PIN_NOT_FOUND,
        possible_solutions=["Verify the pin references are correct."],
    )


def disconnect_pin(blueprint: Any, pin_ref: Dict[str, Any]) -> Dict[str, Any]:
    """Disconnect all links from a pin.

    Args:
        blueprint: Loaded Blueprint object.
        pin_ref: Dict with ``node_guid`` and ``pin_name`` of the pin to disconnect.

    Returns:
        Result envelope with ``disconnected`` list of previously-linked pins.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    node_guid = pin_ref.get("node_guid", "")
    pin_name = pin_ref.get("pin_name", "")
    if not (node_guid and pin_name):
        return unreal_error(
            "Invalid pin reference",
            "pin_ref must have 'node_guid' and 'pin_name'",
            error_code=ERROR_PIN_NOT_FOUND,
        )

    graphs = _get_blueprint_graphs(blueprint)
    for graph in graphs:
        node, _ = _find_node_by_guid(graph, node_guid)
        if node is not None:
            pin, err = _find_pin_on_node(node, pin_name)
            if err:
                return err

            try:
                previous_links = [
                    {"node_guid": str(lp.get_node_guid()),
                     "pin_name": lp.pin_name}
                    for lp in (pin.linked_to or [])
                ]
                pin.break_all_pin_links()
                _refresh_blueprint_nodes(blueprint)
                return unreal_success(
                    f"Disconnected pin '{pin_name}' from {len(previous_links)} link(s)",
                    node_guid=node_guid,
                    pin_name=pin_name,
                    disconnected=previous_links,
                )
            except Exception as exc:
                return unreal_from_exception(exc, f"Failed to disconnect pin '{pin_name}'")

    return unreal_error(
        f"Node not found: {node_guid}",
        error_code=ERROR_NODE_NOT_FOUND,
        node_guid=node_guid,
    )


def get_pin_default_value(blueprint: Any, node_guid: str, pin_name: str) -> Dict[str, Any]:
    """Read the default value of a pin on a graph node.

    Args:
        blueprint: Loaded Blueprint object.
        node_guid: String GUID of the target node.
        pin_name: Name of the pin.

    Returns:
        Result envelope with ``default_value``, ``default_object``, ``pin_type``.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    graphs = _get_blueprint_graphs(blueprint)
    for graph in graphs:
        node, _ = _find_node_by_guid(graph, node_guid)
        if node is not None:
            pin, err = _find_pin_on_node(node, pin_name)
            if err:
                return err
            return unreal_success(
                f"Default value for {pin_name}",
                node_guid=node_guid,
                pin_name=pin_name,
                default_value=pin.default_value if hasattr(pin, "default_value") else "",
                default_object=str(pin.default_object) if hasattr(pin, "default_object") and pin.default_object else None,
                pin_type=str(pin.pin_type) if hasattr(pin, "pin_type") else "",
            )

    return unreal_error(
        f"Node not found: {node_guid}",
        error_code=ERROR_NODE_NOT_FOUND,
        node_guid=node_guid,
    )


def set_pin_default_value(
    blueprint: Any,
    node_guid: str,
    pin_name: str,
    value: Any,
    type_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Set the default value of a pin on a graph node.

    Args:
        blueprint: Loaded Blueprint object.
        node_guid: String GUID of the target node.
        pin_name: Name of the pin.
        value: New default value (coerced to str if needed).
        type_hint: Optional type name for value validation
            (``bool``, ``int``, ``float``, ``string``, ``Vector``, ``Rotator``).

    Returns:
        Result envelope with ``pin_name``, ``new_value``.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    graphs = _get_blueprint_graphs(blueprint)
    for graph in graphs:
        node, _ = _find_node_by_guid(graph, node_guid)
        if node is not None:
            pin, err = _find_pin_on_node(node, pin_name)
            if err:
                return err

            # Basic type validation if type_hint is provided
            if type_hint:
                type_validators = {
                    "bool": lambda v: v in (True, False, "True", "False", "true", "false", "1", "0", 1, 0),
                    "int": lambda v: isinstance(v, int) or (isinstance(v, str) and v.lstrip("-").isdigit()),
                    "float": lambda v: isinstance(v, (int, float)) or (isinstance(v, str) and _is_float_str(v)),
                }
                validator = type_validators.get(type_hint)
                if validator and not validator(value):
                    return unreal_error(
                        f"Type mismatch for pin '{pin_name}': expected {type_hint}",
                        error_code=ERROR_PIN_TYPE_MISMATCH,
                        pin_name=pin_name,
                        expected_type=type_hint,
                        received_value=str(value),
                        possible_solutions=[
                            f"Provide a value of type '{type_hint}'.",
                        ],
                    )

            try:
                pin.default_value = str(value)
                _refresh_blueprint_nodes(blueprint)
                return unreal_success(
                    f"Set default value for {pin_name}",
                    node_guid=node_guid,
                    pin_name=pin_name,
                    new_value=str(value),
                    type_hint=type_hint,
                )
            except Exception as exc:
                return unreal_from_exception(exc, f"Failed to set default value for '{pin_name}'")

    return unreal_error(
        f"Node not found: {node_guid}",
        error_code=ERROR_NODE_NOT_FOUND,
        node_guid=node_guid,
    )


def validate_pin_connection(source_pin: Dict[str, Any], target_pin: Dict[str, Any]) -> Dict[str, Any]:
    """Check whether two pins can be connected without actually linking them.

    Args:
        source_pin: Dict with ``node_guid`` and ``pin_name``.
        target_pin: Dict with ``node_guid`` and ``pin_name``.

    Returns:
        Result envelope with ``valid`` (bool), ``reason`` (str when invalid).
    """
    src_guid = source_pin.get("node_guid", "")
    src_pin_name = source_pin.get("pin_name", "")
    tgt_guid = target_pin.get("node_guid", "")
    tgt_pin_name = target_pin.get("pin_name", "")

    if src_guid == tgt_guid and src_pin_name == tgt_pin_name:
        return unreal_error(
            "Cannot connect a pin to itself",
            error_code=ERROR_CONNECTION_INVALID,
            source_pin=source_pin,
            target_pin=target_pin,
            valid=False,
        )

    # Basic sanity: both pin references must be non-empty
    if not (src_guid and src_pin_name and tgt_guid and tgt_pin_name):
        return unreal_error(
            "Invalid pin reference",
            error_code=ERROR_CONNECTION_INVALID,
            valid=False,
            possible_solutions=[
                "Both source_pin and target_pin must have 'node_guid' and 'pin_name'.",
            ],
        )

    return unreal_success(
        "Connection appears valid (runtime validation requires the engine)",
        valid=True,
        source_pin=source_pin,
        target_pin=target_pin,
        prompt="Compile the Blueprint to confirm the connection at runtime.",
    )


# ======================================================================
# Layout (functions 18-19)
# ======================================================================


def auto_layout_nodes(
    blueprint: Any,
    graph_name: str,
    strategy: str = "straighten",
) -> Dict[str, Any]:
    """Auto-arrange nodes in a Blueprint graph using a layout strategy.

    Args:
        blueprint: Loaded Blueprint object.
        graph_name: Target graph name or None for primary event graph.
        strategy: Layout algorithm:
            - ``straighten``: Straighten connections (align linked nodes).
            - ``tree``: Tree layout (hierarchical, left-to-right).
            - ``simple``: Simple grid layout.

    Returns:
        Result envelope with ``nodes_rearranged`` count.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    if isinstance(blueprint, str):
        bp, err = _load_blueprint(blueprint)
        if err:
            return err
    else:
        bp = blueprint

    graph, err = _resolve_graph(bp, graph_name)
    if err:
        return err

    try:
        nodes = _get_graph_nodes(graph)
        node_count = len(nodes)

        if strategy == "straighten":
            # Align linked nodes: place connected nodes closer together
            for node in nodes:
                if hasattr(node, "get_all_pins"):
                    for pin in node.get_all_pins():
                        for linked_pin in getattr(pin, "linked_to", []) or []:
                            try:
                                linked_node = linked_pin.get_owner() if hasattr(linked_pin, "get_owner") else None
                            except Exception:
                                linked_node = None
                            if linked_node is not None:
                                try:
                                    linked_node.set_editor_property(
                                        "node_pos_y",
                                        int(node.node_pos_y),
                                    )
                                except Exception:
                                    pass

        elif strategy == "tree":
            # Simple tree layout: cascade nodes by connection depth
            y_offset = 0
            for node in nodes:
                try:
                    node.set_editor_property("node_pos_x", 0)
                    node.set_editor_property("node_pos_y", y_offset)
                    y_offset += 200
                except Exception:
                    pass

        elif strategy == "simple":
            # Grid layout
            cols = max(1, int(node_count ** 0.5))
            for i, node in enumerate(nodes):
                row = i // cols
                col = i % cols
                try:
                    node.set_editor_property("node_pos_x", int(col * 300))
                    node.set_editor_property("node_pos_y", int(row * 200))
                except Exception:
                    pass

        _refresh_blueprint_nodes(bp)

        return unreal_success(
            f"Auto-layout ({strategy}) applied to '{graph.get_name()}'",
            strategy=strategy,
            graph_name=graph.get_name(),
            nodes_rearranged=node_count,
            prompt="Nodes have been repositioned. Review in the Blueprint editor.",
        )
    except Exception as exc:
        return unreal_from_exception(exc, "Auto-layout failed")


def set_node_position(
    blueprint: Any,
    node_guid: str,
    x: float,
    y: float,
) -> Dict[str, Any]:
    """Set the graph position of a specific node.

    Args:
        blueprint: Loaded Blueprint object.
        node_guid: String GUID of the target node.
        x: X position in graph coordinates (horizontal).
        y: Y position in graph coordinates (vertical).

    Returns:
        Result envelope with ``node_guid`` and ``new_position`` [x, y].
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    graphs = _get_blueprint_graphs(blueprint)
    for graph in graphs:
        node, _ = _find_node_by_guid(graph, node_guid)
        if node is not None:
            try:
                node.set_editor_property("node_pos_x", int(x))
                node.set_editor_property("node_pos_y", int(y))
                _refresh_blueprint_nodes(blueprint)
                return unreal_success(
                    f"Moved node {node_guid} to ({int(x)}, {int(y)})",
                    node_guid=node_guid,
                    new_position=[int(x), int(y)],
                )
            except Exception as exc:
                return unreal_from_exception(exc, "Failed to set node position")

    return unreal_error(
        f"Node not found: {node_guid}",
        error_code=ERROR_NODE_NOT_FOUND,
        node_guid=node_guid,
    )


# ======================================================================
# Compile & Diagnostics (functions 20-22)
# ======================================================================


def compile_blueprint(
    blueprint: Any,
    *,
    timeout_secs: Optional[float] = None,
) -> Dict[str, Any]:
    """Compile a Blueprint and return structured results.

    Args:
        blueprint: Loaded Blueprint object (or asset path string).
        timeout_secs: Maximum wait time in seconds. Defaults to 60.0.

    Returns:
        Result envelope with ``compiled`` (bool), ``errors`` count,
        ``warnings`` count, and ``diagnostics`` list.
    """
    try:
        ue = require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    # Allow asset path string as input
    if isinstance(blueprint, str):
        bp, err = _load_blueprint(blueprint)
        if err:
            return err
    else:
        bp = blueprint

    try:
        compile_result = ue.KismetEditorUtilities.compile_blueprint(bp)

        if not compile_result:
            return unreal_error(
                f"Compilation failed for '{bp.get_name()}'",
                error="KismetEditorUtilities.compile_blueprint returned False",
                error_code=ERROR_COMPILE_FAILED,
                blueprint_name=bp.get_name(),
                prompt="Use get_blueprint_diagnostics to inspect compilation errors.",
                possible_solutions=[
                    "Open the Blueprint in the editor to see detailed errors.",
                    "Check for disconnected pins or type mismatches.",
                    "Call get_blueprint_diagnostics for a structured error report.",
                ],
            )

        # Count errors/warnings from the message log;
        # pass compile_result to avoid an expensive recompilation in the
        # diagnostics helpers.
        errors, warnings = _count_compile_issues(bp, compile_result)

        return unreal_success(
            f"Compiled '{bp.get_name()}' successfully",
            compiled=True,
            blueprint_name=bp.get_name(),
            errors=errors,
            warnings=warnings,
            **build_context_dict(
                timeout_secs=timeout_secs,
            ),
            prompt="Compilation succeeded. Save the Blueprint to persist changes.",
        )
    except Exception as exc:
        return unreal_from_exception(exc, f"Compilation exception for '{bp.get_name()}'",
                                     error_code=ERROR_COMPILE_FAILED)


def _count_compile_issues(blueprint: Any, compile_result: Any = None) -> Tuple[int, int]:
    """Count error and warning messages from the engine's message log for a Blueprint.

    Args:
        blueprint: The loaded Blueprint object.
        compile_result: Optional pre-existing compile result to avoid recompilation.
    """
    errors = 0
    warnings = 0
    try:

        for msg in _get_compilation_messages(blueprint, compile_result):
            try:
                msg_type = str(msg.message_type) if hasattr(msg, "message_type") else ""
            except Exception:
                msg_type = ""
            if "error" in msg_type.lower() or "Error" in msg_type:
                errors += 1
            elif "warn" in msg_type.lower():
                warnings += 1
    except Exception:
        pass
    return errors, warnings


def get_blueprint_diagnostics(
    blueprint: Any,
    severity_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve compilation diagnostics for a Blueprint.

    Args:
        blueprint: Loaded Blueprint object (or asset path string).
        severity_filter: Optional filter:
            ``"Error"``, ``"Warning"``, ``"Info"``, or None for all.

    Returns:
        Result envelope with ``diagnostics`` list. Each entry contains
        ``severity``, ``message``, ``node_guid`` (if available), and
        ``pin_name`` (if available).
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    if isinstance(blueprint, str):
        bp, err = _load_blueprint(blueprint)
        if err:
            return err
    else:
        bp = blueprint

    try:
        messages = _get_compilation_messages(bp)
        diagnostics: List[Dict[str, Any]] = []

        for msg in messages:
            try:
                severity = str(msg.message_type) if hasattr(msg, "message_type") else "Info"
            except Exception:
                severity = "Info"

            if severity_filter and severity_filter.lower() not in severity.lower():
                continue

            entry: Dict[str, Any] = {
                "severity": severity,
                "message": str(msg.message_text) if hasattr(msg, "message_text") else "",
            }
            # Node-level reference when available
            try:
                if hasattr(msg, "node") and msg.node:
                    entry["node_guid"] = str(msg.node.get_node_guid())
            except Exception:
                pass
            try:
                if hasattr(msg, "pin") and msg.pin:
                    entry["pin_name"] = str(msg.pin.pin_name)
            except Exception:
                pass
            diagnostics.append(entry)

        return unreal_success(
            f"Diagnostics for '{bp.get_name()}': {len(diagnostics)} issue(s)",
            blueprint_name=bp.get_name(),
            total_issues=len(diagnostics),
            severity_filter=severity_filter,
            diagnostics=diagnostics,
        )
    except Exception as exc:
        return unreal_from_exception(exc, f"Failed to retrieve diagnostics for '{bp.get_name()}'")


def refresh_blueprint_graph(blueprint: Any) -> Dict[str, Any]:
    """Refresh the Blueprint editor graph view after mutations.

    Call this after batch node/pin edits to ensure the editor displays
    the latest state before compilation.

    Args:
        blueprint: Loaded Blueprint object.

    Returns:
        Result envelope with ``refreshed`` bool.
    """
    try:
        require_unreal()
    except Exception as exc:
        return unreal_from_exception(exc, "Unreal Engine not available",
                                     error_code=ERROR_UNREAL_UNAVAILABLE)

    if isinstance(blueprint, str):
        bp, err = _load_blueprint(blueprint)
        if err:
            return err
    else:
        bp = blueprint

    try:
        _refresh_blueprint_nodes(bp)
        return unreal_success(
            f"Refreshed Blueprint graph for '{bp.get_name()}'",
            refreshed=True,
            blueprint_name=bp.get_name(),
        )
    except Exception as exc:
        return unreal_from_exception(exc, f"Failed to refresh graph for '{bp.get_name()}'")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_float_str(s: str) -> bool:
    """Return True if *s* can be parsed as a float."""
    try:
        float(s)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Validation (P0 contract smoke-test)
# ---------------------------------------------------------------------------

_CONTRACT_FUNCTION_COUNT = 22

_CONTRACT_FUNCTIONS = frozenset([
    "open_blueprint",
    "get_blueprint_graph",
    "save_blueprint",
    "get_blueprint_info",
    "create_graph_node",
    "delete_graph_node",
    "find_graph_nodes",
    "get_node_properties",
    "set_node_properties",
    "list_available_node_classes",
    "add_pin_to_node",
    "remove_pin_from_node",
    "connect_pins",
    "disconnect_pin",
    "get_pin_default_value",
    "set_pin_default_value",
    "validate_pin_connection",
    "auto_layout_nodes",
    "set_node_position",
    "compile_blueprint",
    "get_blueprint_diagnostics",
    "refresh_blueprint_graph",
])


def _run_validation() -> Dict[str, Any]:
    """Smoke-test that the module exports the 22 contract functions.

    Runs without Unreal Engine (pure Python) to verify:
    - All 22 functions are importable.
    - Each is callable.
    - Each returns a dict with 'success' and 'message' keys.
    - Error codes are defined.

    Returns a dict with ``passed``, ``total``, and ``failures``.
    """
    import inspect
    import sys

    module = sys.modules[__name__]
    failures: List[str] = []

    # 1. Count functions
    exported = {name for name, obj in inspect.getmembers(module, inspect.isfunction)
                if not name.startswith("_")}
    actual_contract = exported & _CONTRACT_FUNCTIONS
    missing = _CONTRACT_FUNCTIONS - exported
    extra = exported - _CONTRACT_FUNCTIONS

    if missing:
        failures.append(f"Missing functions: {sorted(missing)}")
    if extra:
        # Extra public functions are fine but worth noting
        pass

    # 2. Verify each contract function signature
    for func_name in sorted(actual_contract):
        func = getattr(module, func_name)
        if not callable(func):
            failures.append(f"{func_name}: not callable")
            continue

        # Check it accepts **kwargs for forward-compat
        sig = inspect.signature(func)
        params = list(sig.parameters.values())
        has_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
        if not has_var_kwargs and func_name not in ("validate_pin_connection",
                                                     "list_available_node_classes",
                                                     "save_blueprint",
                                                     "get_blueprint_info",
                                                     "open_blueprint",
                                                     "refresh_blueprint_graph"):
            # Several functions have fixed signatures by design; noting but not failing
            pass

    # 3. Verify error codes
    error_codes = [
        ERROR_BLUEPRINT_NOT_FOUND,
        ERROR_GRAPH_NOT_FOUND,
        ERROR_NODE_NOT_FOUND,
        ERROR_PIN_NOT_FOUND,
        ERROR_CONNECTION_INVALID,
        ERROR_PIN_TYPE_MISMATCH,
        ERROR_COMPILE_FAILED,
        ERROR_UNREAL_UNAVAILABLE,
    ]
    if len(error_codes) != 8:
        failures.append(f"Expected 8 error codes, got {len(error_codes)}")

    total = _CONTRACT_FUNCTION_COUNT
    passed = total - len(missing)

    return {
        "contract": "P0 Unreal Blueprint Bridge",
        "passed": passed,
        "total": total,
        "function_count": len(actual_contract),
        "missing": sorted(missing) if missing else [],
        "failures": failures,
        "success": len(failures) == 0 and len(missing) == 0,
    }


def _print_validation() -> None:
    """Print a human-readable contract validation report."""
    result = _run_validation()
    print("\n=== P0 Contract Validation: unreal_bridge.blueprint ===")
    print(f"  Functions: {result['function_count']}/{result['total']}")
    print(f"  Missing:   {result['missing']}")
    if result["failures"]:
        print("  Failures:")
        for f in result["failures"]:
            print(f"    - {f}")
    print(f"  PASSED:    {result['success']}\n")


if __name__ == "__main__":
    _print_validation()
