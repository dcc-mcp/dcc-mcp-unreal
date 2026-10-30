"""Read-only PCG Python-surface observations; never execute authoring probes.

Keep Unreal and HTTP imports out of this module. Importing the adapter must not
load optional plugins or contact the official MCP service.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any

# These are documented Python names, not official MCP tool names. Presence is
# useful evidence, but neither an API signature check nor native acceptance.
_SURFACES = {
    "graph": {
        "PCGGraph": ("add_node_of_type", "add_edge", "remove_edge", "remove_node"),
        "PCGGraphFactory": (),
        "PCGNode": ("get_settings", "get_node_position"),
    },
    "generation": {"PCGComponent": ("generate", "get_generated_graph_output")},
    "grammar": {"PCGGrammarSelection": (), "PCGSubdivisionSubmodule": (), "PCGSubdivideSplineSettings": ()},
    "spline": {
        "SplineComponent": ("get_number_of_spline_points", "get_location_at_distance_along_spline"),
        "PCGSplineData": (),
        "PCGSplineSamplerSettings": (),
        "PCGSplineSamplerParams": (),
    },
    "pathfinding": {"PCGPathfindingSettings": (), "PCGPathfindingCostFunctionMode": ()},
}
_DOCUMENTED_VERSIONS = {"graph": "5.2", "generation": "5.3", "grammar": "5.5", "spline": "5.2", "pathfinding": "5.5"}
_PLUGIN_NAMES = ("PCG", "PCGToolset", "ModelContextProtocol")


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:400]


def _member(owner: Any, name: str) -> tuple[Any, dict]:
    """Inspect fixed names only; never instantiate classes or run descriptors."""
    try:
        value = inspect.getattr_static(owner, name)
    except AttributeError:
        return None, {"status": "unavailable", "reason": "Not exposed on the inspected Python surface"}
    except Exception as exc:
        return None, {"status": "unknown", "reason": _error_text(exc)}
    if value is None:
        return None, {"status": "unavailable", "reason": "Python attribute is None"}
    return value, {"status": "available"}


def _query(unreal_module: Any, class_name: str, method_name: str, *args: Any) -> tuple[Any, str | None]:
    """Call only allowlisted read-only engine/plugin metadata queries."""
    try:
        owner = getattr(unreal_module, class_name, None)
        method = getattr(owner, method_name, None)
        if not callable(method):
            return None, f"unreal.{class_name}.{method_name} is not exposed"
        return method(*args), None
    except Exception as exc:
        return None, _error_text(exc)


def _engine_identity(unreal_module: Any) -> dict:
    raw, error = _query(unreal_module, "SystemLibrary", "get_engine_version")
    if error or not isinstance(raw, str) or not raw:
        return {"status": "unknown", "version": None, "reason": error or "No engine version string returned"}
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", raw)
    version = [int(part) if part is not None else 0 for part in match.groups()] if match else None
    return {
        "status": "available",
        "version": raw[:256],
        "version_components": version,
        "source": "unreal.SystemLibrary.get_engine_version",
        "used_as_feature_gate": False,
    }


def _plugins(unreal_module: Any) -> dict:
    names, names_error = _query(unreal_module, "PluginBlueprintLibrary", "get_enabled_plugin_names")
    enabled = None
    if names_error is None:
        try:
            if names is None or isinstance(names, (str, bytes)):
                raise ValueError("Expected a plugin-name array")
            enabled = {str(name) for name in names}
        except Exception as exc:
            names_error = _error_text(exc)

    result = {}
    for name in _PLUGIN_NAMES:
        path, error = _query(unreal_module, "PluginBlueprintLibrary", "get_plugin_descriptor_file_path", name)
        entry = {
            "installed": None,
            "enabled": name in enabled if enabled is not None else None,
            "descriptor_path": None,
            "source": "unreal.PluginBlueprintLibrary (current process) and descriptor file existence",
        }
        reasons = []
        if names_error:
            reasons.append(names_error)
        if error:
            entry["discovered"] = None
            reasons.append(error)
        elif path is None or path == "":
            entry["discovered"] = False
            reasons.append("Registry returned no descriptor; disk installation was not exhaustively searched")
        elif isinstance(path, str):
            entry["discovered"] = True
            entry["descriptor_path"] = path
            try:
                entry["installed"] = Path(path).is_file()
            except OSError as exc:
                reasons.append(_error_text(exc))
        else:
            entry["discovered"] = None
            reasons.append("Registry returned an unexpected descriptor path type")
        entry["reasons"] = reasons
        result[name] = entry
    return result


def collect_pcg_capabilities(unreal_module: Any) -> dict:
    """Observe a fixed reflection surface without creating or loading assets.

    Missing Python exposure is not proof that the equivalent native C++ or
    official MCP API is absent. Class/property lookup is deliberately static;
    dynamic-only wrappers remain unavailable here until a separate safe query
    establishes them.
    """
    features = {}
    for feature_name, surface in _SURFACES.items():
        checks = {}
        for class_name, methods in surface.items():
            owner, check = _member(unreal_module, class_name)
            if owner is not None and not inspect.isclass(owner):
                owner = None
                check = {"status": "unavailable", "reason": "Python attribute is not a class"}
            checks[class_name] = check
            for method_name in methods:
                key = f"{class_name}.{method_name}"
                if owner is None:
                    checks[key] = {"status": check["status"], "reason": "Owning Python class was not observed"}
                    continue
                method, method_check = _member(owner, method_name)
                if method_check["status"] == "available" and not (
                    callable(method) or isinstance(method, (classmethod, staticmethod))
                ):
                    method_check = {"status": "unavailable", "reason": "Attribute is not a callable method"}
                checks[key] = method_check
        statuses = {check["status"] for check in checks.values()}
        status = next(iter(statuses)) if len(statuses) == 1 else "partial"
        features[feature_name] = {
            "python_surface_status": status,
            "checks": checks,
            "documented_api_version": _DOCUMENTED_VERSIONS[feature_name],
            "execution_verified": False,
        }

    # A known version-dependent property is checked without constructing node
    # settings or assuming a property's presence from the engine version.
    pathfinding_class, class_check = _member(unreal_module, "PCGPathfindingSettings")
    if pathfinding_class is None:
        mapping_check = dict(class_check)
    else:
        _, mapping_check = _member(pathfinding_class, "goal_mapping_mode")
    features["pathfinding"]["optional_properties"] = {"goal_mapping_mode": mapping_check}

    return {
        "schema_version": 1,
        "evidence": "Read-only Python reflection and metadata queries; no authoring API was executed",
        "engine": _engine_identity(unreal_module),
        "plugins": _plugins(unreal_module),
        "features": features,
        "execution_verified": False,
        "native_bridge_verified": False,
        "official_mcp": {
            "status": "unknown",
            "tool_schemas": "not_queried",
            "reason": "No HTTP request or service startup is performed by this inspection",
            "next_tool": "unreal_official_mcp__official_mcp_bridge",
            "discovery_operations": ["status", "list_toolsets", "describe_toolset"],
        },
        "limitations": [
            "Available means only the listed Python names were observed, not full feature support or signature compatibility.",
            "Unavailable Python names do not rule out a native or official MCP route.",
            "Documented API versions are reference points, not minimum-version gates or tested-version claims.",
            "No graph, node, component or settings object was created; no generation, save or plugin enablement occurred.",
        ],
    }
