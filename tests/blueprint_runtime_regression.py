"""PIP-2919 Blueprint Bridge Runtime Regression.
Run with UnrealEditor-Cmd.exe:
    UnrealEditor-Cmd.exe <project.uproject> -ExecutePythonScript=<this_file> -stdout -unattended -nullrhi

Validates all 22 unreal_bridge.blueprint functions in-engine.
Version-aware: on UE < 5.5, node-level API (K2Node_*, EdGraph.get_all_nodes,
EdGraph.add_node) is unavailable — the bridge must return structured error
envelopes instead of crashing.
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure dcc-mcp-unreal is importable inside UE
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent
_src_dir = str(_project_root / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# dcc_mcp_core dependency — ensure it is importable inside UE
_core_src = str(Path(__file__).resolve().parent.parent.parent / "dcc-mcp-core-temp" / "python")
if Path(_core_src).is_dir() and _core_src not in sys.path:
    sys.path.insert(0, _core_src)

RESULTS: list = []
TEST_BP_PATH = "/Game/BP_RegressionTest_PIP2919"
TEST_BP_ASSET = f"{TEST_BP_PATH}.{TEST_BP_PATH.split('/')[-1]}"

# ── Engine version cache ──────────────────────────────────────────
_ENGINE_VERSION: Optional[Tuple[int, int]] = None


def _get_engine_version() -> Tuple[int, int]:
    """Return (major, minor) engine version tuple."""
    global _ENGINE_VERSION
    if _ENGINE_VERSION is not None:
        return _ENGINE_VERSION
    try:
        import unreal
        ver = unreal.SystemLibrary.get_engine_version()
        m = re.match(r"(\d+)\.(\d+)", ver)
        if m:
            _ENGINE_VERSION = (int(m.group(1)), int(m.group(2)))
        else:
            _ENGINE_VERSION = (5, 0)  # fallback
    except Exception:
        _ENGINE_VERSION = (5, 0)
    return _ENGINE_VERSION


def _ue_major() -> int:
    return _get_engine_version()[0]


def _ue_minor() -> int:
    return _get_engine_version()[1]


def _node_api_available() -> bool:
    """True when the engine exposes K2Node_* classes and EdGraph node API."""
    major, minor = _get_engine_version()
    return major > 5 or (major == 5 and minor >= 5)


def _ctx(result: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Read a value from the ``context`` sub-dict of an unreal_success/unreal_error envelope."""
    return result.get("context", {}).get(key, default)


def record(name: str, success: bool, detail: str = "") -> None:
    RESULTS.append({"test": name, "success": success, "detail": detail})
    status = "PASS" if success else "FAIL"
    # Write to both UE log and stdout
    print(f"[{status}] {name}")
    if detail:
        print(f"       {detail[:200]}")


def _ensure_test_blueprint() -> tuple:
    """Create or find a test Blueprint asset. Returns (asset_path, blueprint_object)."""
    import unreal

    # Try to load existing
    if unreal.EditorAssetLibrary.does_asset_exist(TEST_BP_ASSET):
        bp = unreal.EditorAssetLibrary.load_asset(TEST_BP_PATH)
        if bp:
            record("create_test_bp", True, f"Loaded existing: {TEST_BP_PATH}")
            return TEST_BP_PATH, bp

    # Create new Blueprint
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.Actor)

    bp = asset_tools.create_asset(
        asset_name="BP_RegressionTest_PIP2919",
        package_path="/Game/",
        asset_class=unreal.Blueprint,
        factory=factory,
    )

    if bp:
        unreal.EditorAssetLibrary.save_asset(TEST_BP_PATH)
        # UE 5.3: EventGraph and other graphs are only initialised after
        # save + reload.  The in-memory UBlueprint from the factory does
        # not have graphs populated yet; forcing a disk reload fixes it.
        if hasattr(unreal.EditorAssetLibrary, "unload_asset"):
            unreal.EditorAssetLibrary.unload_asset(TEST_BP_PATH)
        bp = unreal.EditorAssetLibrary.load_asset(TEST_BP_PATH)
        record("create_test_bp", True, f"Created: {TEST_BP_PATH} (parent: Actor)")
        return TEST_BP_PATH, bp
    else:
        record("create_test_bp", False, "Failed to create Blueprint asset")
        return None, None


def run_regression() -> dict:
    """Run the full pipeline regression."""
    # ── Phase 0: Import & engine check ────────────────────────────
    try:
        from dcc_mcp_unreal.unreal_bridge.blueprint import (
            add_pin_to_node,
            auto_layout_nodes,
            compile_blueprint,
            connect_pins,
            create_graph_node,
            delete_graph_node,
            disconnect_pin,
            find_graph_nodes,
            get_blueprint_diagnostics,
            get_blueprint_graph,
            get_blueprint_info,
            get_node_properties,
            get_pin_default_value,
            list_available_node_classes,
            open_blueprint,
            refresh_blueprint_graph,
            remove_pin_from_node,
            save_blueprint,
            set_node_position,
            set_node_properties,
            set_pin_default_value,
            validate_pin_connection,
        )
        record("import_module", True, "All 22 functions imported")
    except Exception as exc:
        record("import_module", False, str(exc))
        return _summary()

    try:
        import unreal
        ver_str = unreal.SystemLibrary.get_engine_version()
        can_node = _node_api_available()
        record("engine_available", True,
               f"UE {ver_str}  node_api={'yes' if can_node else 'NO'}")
    except ImportError as exc:
        record("engine_available", False, str(exc))
        return _summary()

    # ── Phase 0.5: Create test Blueprint ──────────────────────────
    asset_path, bp_obj = _ensure_test_blueprint()
    if not asset_path:
        return _summary()

    node_api = _node_api_available()

    # ── Phase 1: Graph Lifecycle ──────────────────────────────────
    # 1a. list_available_node_classes
    try:
        classes = list_available_node_classes()
        if isinstance(classes, dict) and classes.get("success"):
            # Extra kwargs land inside ``context`` sub-dict (unreal_success contract)
            node_classes = _ctx(classes, "node_classes", [])
            count = len(node_classes)
            if node_api:
                # On supported engines the hardcoded list should be non-empty
                record("list_available_node_classes", count > 0, f"{count} node classes returned")
            else:
                # UE < 5.5: hardcoded list still returned (the bridge lists
                # canonical names regardless of whether the engine exposes them)
                record("list_available_node_classes", count > 0, f"{count} node classes (UE<5.5; classes not runtime-verified)")
            if count > 0:
                sample = node_classes[:3] if len(node_classes) >= 3 else node_classes
                record("node_class_sample", True, str(sample))
        else:
            record("list_available_node_classes", False, f"response: {str(classes)[:200]}")
    except Exception as exc:
        record("list_available_node_classes", False, str(exc))

    # 1b. get_blueprint_info
    try:
        info = get_blueprint_info(asset_path)
        if info.get("success"):
            record("get_blueprint_info", True, f"class={info.get('blueprint_class', '?')}")
        else:
            record("get_blueprint_info", False, str(info)[:200])
    except Exception as exc:
        record("get_blueprint_info", False, str(exc))

    # 1c. open_blueprint
    bp_handle = None
    try:
        result = open_blueprint(asset_path)
        if result.get("success"):
            bp_handle = result
            record("open_blueprint", True, f"graphs={result.get('graphs', [])}")
        else:
            record("open_blueprint", False, str(result)[:200])
    except Exception as exc:
        record("open_blueprint", False, str(exc))

    # 1d. get_blueprint_graph
    try:
        result = get_blueprint_graph(asset_path)
        if result.get("success"):
            # ``node_count`` and ``nodes`` are inside the context sub-dict
            graph_count = _ctx(result, "node_count", 0)
            graph_name = _ctx(result, "graph_name", "?")
            record("get_blueprint_graph", True,
                   f"graph='{graph_name}' nodes={graph_count}")
        else:
            record("get_blueprint_graph", False, str(result)[:200])
    except Exception as exc:
        record("get_blueprint_graph", False, str(exc))

    # ── Phase 2: Node CRUD ────────────────────────────────────────
    n1_guid = None
    n2_guid = None

    # 2a. create_graph_node — PrintString for safety
    try:
        result = create_graph_node(asset_path, graph_name=None, node_class="K2Node_CallFunction", position=(100, 200))
        if result.get("success"):
            n1_guid = _ctx(result, "node_guid")
            node_info = _ctx(result, "node_info", {})
            func = node_info.get("function_name", "?")
            record("create_node_1", True, f"guid={n1_guid[:16] if n1_guid else '?'}... func={func}")
        else:
            # On UE < 5.5, K2Node_* classes are not exposed — graceful
            # error envelope is the *correct* behaviour.
            error_code = _ctx(result, "error_code", "")
            if not node_api and error_code in ("NODE_NOT_FOUND",):
                record("create_node_1", True,
                       f"K2Node_* unavailable on UE {_ue_major()}.{_ue_minor()} (expected; graceful error)")
            else:
                record("create_node_1", False, str(result)[:200])
    except Exception as exc:
        record("create_node_1", False, str(exc))

    # 2b. create_graph_node — CustomEvent
    try:
        result = create_graph_node(asset_path, graph_name=None, node_class="K2Node_CustomEvent", position=(400, 0))
        if result.get("success"):
            n2_guid = _ctx(result, "node_guid")
            record("create_node_2", True, f"guid={n2_guid[:16] if n2_guid else '?'}...")
        else:
            error_code = _ctx(result, "error_code", "")
            if not node_api and error_code in ("NODE_NOT_FOUND",):
                record("create_node_2", True,
                       f"K2Node_* unavailable on UE {_ue_major()}.{_ue_minor()} (expected; graceful error)")
            else:
                record("create_node_2", False, str(result)[:200])
    except Exception as exc:
        record("create_node_2", False, str(exc))

    # 2c. find_graph_nodes
    try:
        result = find_graph_nodes(asset_path, filters={"node_class": "CallFunction"})
        if result.get("success"):
            count = len(_ctx(result, "nodes", []))
            if node_api:
                record("find_graph_nodes", count > 0, f"{count} CallFunction nodes")
            else:
                # UE < 5.5: EdGraph.get_all_nodes is unavailable — graph
                # enumeration returns empty.  This is expected.
                record("find_graph_nodes", True,
                       f"{count} CallFunction nodes (UE<5.5: graph enumeration unavailable; 0 expected)")
        else:
            record("find_graph_nodes", False, str(result)[:200])
    except Exception as exc:
        record("find_graph_nodes", False, str(exc))

    # 2d. get_node_properties
    if n1_guid:
        try:
            result = get_node_properties(asset_path, n1_guid)
            if result.get("success"):
                record("get_node_properties", True, f"class={_ctx(result, 'node_class', '?')}")
            else:
                record("get_node_properties", False, str(result)[:200])
        except Exception as exc:
            record("get_node_properties", False, str(exc))

    # 2e. set_node_properties
    if n1_guid:
        try:
            result = set_node_properties(asset_path, n1_guid, {"node_comment": "PIP-2919 regression test"})
            if result.get("success"):
                record("set_node_properties", True, "comment set")
            else:
                record("set_node_properties", False, str(result)[:200])
        except Exception as exc:
            record("set_node_properties", False, str(exc))

    # ── Phase 3: Pin Operations ───────────────────────────────────
    # 3a. connect_pins (exec then→execute)
    if n1_guid and n2_guid:
        try:
            result = connect_pins(
                asset_path,
                {"node_guid": n2_guid, "pin_name": "then"},
                {"node_guid": n1_guid, "pin_name": "execute"},
            )
            if result.get("success"):
                record("connect_pins", True)
            else:
                record("connect_pins", False, str(result)[:200])
        except Exception as exc:
            record("connect_pins", False, str(exc))

    # 3b. validate_pin_connection
    if n1_guid and n2_guid:
        try:
            result = validate_pin_connection(
                asset_path,
                {"node_guid": n2_guid, "pin_name": "then"},
                {"node_guid": n1_guid, "pin_name": "execute"},
            )
            if result.get("success"):
                record("validate_pin_connection", result.get("valid", False), f"valid={result.get('valid')}")
            else:
                record("validate_pin_connection", False, str(result)[:200])
        except Exception as exc:
            record("validate_pin_connection", False, str(exc))

    # 3c. disconnect_pin
    if n1_guid and n2_guid:
        try:
            result = disconnect_pin(asset_path, n1_guid, "execute")
            if result.get("success"):
                record("disconnect_pin", True)
            else:
                record("disconnect_pin", False, str(result)[:200])
        except Exception as exc:
            record("disconnect_pin", False, str(exc))

    # 3d. add_pin_to_node
    if n1_guid:
        try:
            result = add_pin_to_node(asset_path, n1_guid, "TestInput", "input", "bool")
            if result.get("success"):
                record("add_pin_to_node", True, f"pin={result.get('pin_name', '?')}")
            else:
                record("add_pin_to_node", False, str(result)[:200])
        except Exception as exc:
            record("add_pin_to_node", False, str(exc))

    # 3e. set_pin_default_value
    if n1_guid:
        try:
            result = set_pin_default_value(asset_path, n1_guid, "TestInput", True)
            if result.get("success"):
                record("set_pin_default_value", True)
            else:
                record("set_pin_default_value", False, str(result)[:200])
        except Exception as exc:
            record("set_pin_default_value", False, str(exc))

    # 3f. get_pin_default_value
    if n1_guid:
        try:
            result = get_pin_default_value(asset_path, n1_guid, "TestInput")
            if result.get("success"):
                record("get_pin_default_value", True, f"value={result.get('default_value')}")
            else:
                record("get_pin_default_value", False, str(result)[:200])
        except Exception as exc:
            record("get_pin_default_value", False, str(exc))

    # 3g. remove_pin_from_node
    if n1_guid:
        try:
            result = remove_pin_from_node(asset_path, n1_guid, "TestInput")
            if result.get("success"):
                record("remove_pin_from_node", True)
            else:
                record("remove_pin_from_node", False, str(result)[:200])
        except Exception as exc:
            record("remove_pin_from_node", False, str(exc))

    # ── Phase 4: Layout ───────────────────────────────────────────
    # 4a. set_node_position
    if n1_guid:
        try:
            result = set_node_position(asset_path, n1_guid, (300, 150))
            if result.get("success"):
                record("set_node_position", True)
            else:
                record("set_node_position", False, str(result)[:200])
        except Exception as exc:
            record("set_node_position", False, str(exc))

    # 4b. auto_layout_nodes
    try:
        result = auto_layout_nodes(asset_path, graph_name=None, strategy="straighten")
        if result.get("success"):
            record("auto_layout_nodes", True, "straighten applied")
        else:
            record("auto_layout_nodes", False, str(result)[:200])
    except Exception as exc:
        record("auto_layout_nodes", False, str(exc))

    # ── Phase 5: Compile & Diagnostics ────────────────────────────
    # 5a. compile_blueprint
    try:
        result = compile_blueprint(asset_path)
        if result.get("success"):
            record("compile_blueprint", True, "compilation succeeded")
        else:
            diag_prompt = str(result.get("prompt", ""))
            has_chain = "get_blueprint_diagnostics" in diag_prompt.lower()
            error_code = _ctx(result, "error_code", "")
            if not node_api and error_code:
                # UE < 5.5: KismetEditorUtilities may not be fully exposed —
                # graceful error envelope is the expected behaviour.
                record("compile_blueprint", True,
                       f"UE<5.5 compile delegate unavailable (expected; error_code={error_code})")
            else:
                record("compile_blueprint", has_chain, f"failed with diagnostics chain: {has_chain}")
    except Exception as exc:
        record("compile_blueprint", False, str(exc))

    # 5b. get_blueprint_diagnostics
    try:
        result = get_blueprint_diagnostics(asset_path)
        if result.get("success"):
            diag_count = len(_ctx(result, "diagnostics", []))
            record("get_blueprint_diagnostics", True, f"{diag_count} diagnostics")
        else:
            record("get_blueprint_diagnostics", False, str(result)[:200])
    except Exception as exc:
        record("get_blueprint_diagnostics", False, str(exc))

    # 5c. refresh_blueprint_graph
    try:
        result = refresh_blueprint_graph(asset_path)
        if result.get("success"):
            record("refresh_blueprint_graph", True)
        else:
            record("refresh_blueprint_graph", False, str(result)[:200])
    except Exception as exc:
        record("refresh_blueprint_graph", False, str(exc))

    # ── Phase 6: Cleanup ──────────────────────────────────────────
    # Delete test nodes
    if n1_guid:
        try:
            result = delete_graph_node(asset_path, n1_guid)
            record("delete_graph_node_1", result.get("success", False), str(result)[:200])
        except Exception as exc:
            record("delete_graph_node_1", False, str(exc))

    if n2_guid:
        try:
            result = delete_graph_node(asset_path, n2_guid)
            record("delete_graph_node_2", result.get("success", False), str(result)[:200])
        except Exception as exc:
            record("delete_graph_node_2", False, str(exc))

    # Save
    try:
        result = save_blueprint(asset_path)
        record("save_blueprint", result.get("success", False), str(result)[:200])
    except Exception as exc:
        record("save_blueprint", False, str(exc))

    return _summary()


def _summary() -> dict:
    passed = sum(1 for r in RESULTS if r["success"])
    failed = sum(1 for r in RESULTS if not r["success"])
    return {
        "passed": passed,
        "failed": failed,
        "total": len(RESULTS),
        "results": RESULTS,
        "all_passed": failed == 0,
    }


def main() -> None:
    try:
        summary = run_regression()
    except Exception:
        traceback.print_exc()
        summary = {"passed": 0, "failed": len(RESULTS), "total": len(RESULTS), "results": RESULTS, "all_passed": False}

    # Write JSON result
    result_path = Path(__file__).with_suffix(".result.json")
    result_path.write_text(json.dumps(summary, indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    if not summary["all_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
