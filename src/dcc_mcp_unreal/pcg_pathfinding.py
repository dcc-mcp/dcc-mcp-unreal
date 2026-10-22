"""Bounded input validation and transient native PCG Pathfinding preflight.

This is not a path solver, AI navigation adapter, or graph execution API. No
Unreal import occurs until the caller explicitly supplies the running host.
"""

from __future__ import annotations

import math
import re
from typing import Any

MAX_POINTS = 4096
MAX_ENDPOINTS = 64
MAX_PINS = 64
_ATTRIBUTE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_ENUM = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_MODES = ("DISTANCE", "FITNESS_SCORE", "COST_MULTIPLIER")
_OPTIONS = {
    "search_distance",
    "cost_function_mode",
    "cost_attribute",
    "heuristic_weight",
    "maximum_fitness_penalty_factor",
    "accept_partial_path",
    "copy_originating_points",
    "output_as_spline",
    "spline_mode",
    "goal_mapping_mode",
    "seed",
}


class PathfindingValidationError(ValueError):
    """The bounded adapter input contract was not satisfied."""


class PathfindingHostError(RuntimeError):
    """The current host could not verify the requested transient configuration."""


def _object(value: Any, allowed: set[str], required: set[str], name: str) -> dict:
    if not isinstance(value, dict):
        raise PathfindingValidationError(f"{name} must be an object")
    if set(value) - allowed or required - set(value):
        raise PathfindingValidationError(f"{name} has unknown or missing fields")
    return value


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PathfindingValidationError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise PathfindingValidationError(f"{name} must be a finite number") from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise PathfindingValidationError(f"{name} must be finite and within [{minimum}, {maximum}]")
    return result


def _vector(value: Any, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise PathfindingValidationError(f"{name} must contain exactly three coordinates in centimeters")
    return [_number(component, name, -1e9, 1e9) for component in value]


def _attribute(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ATTRIBUTE.fullmatch(value) or value.casefold() == "none":
        raise PathfindingValidationError(f"{name} must be a plain named attribute, not a property/expression selector")
    return value


def _endpoint(value: Any, name: str) -> dict:
    value = _object(value, {"location", "attribute", "values"}, set(), name)
    if set(value) == {"location"}:
        return {"location": _vector(value["location"], name)}
    if set(value) != {"attribute", "values"}:
        raise PathfindingValidationError(f"{name} must specify either location or attribute and values")
    attribute = _attribute(value["attribute"], name)
    values = value["values"]
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_ENDPOINTS:
        raise PathfindingValidationError(f"{name}.values must contain 1..{MAX_ENDPOINTS} vectors")
    return {"attribute": attribute, "values": [_vector(vector, name) for vector in values]}


def validate_pathfinding_request(point_cloud: Any, start: Any, goal: Any, settings: Any) -> dict:
    """Validate JSON descriptors without constructing or executing Unreal data.

    Coordinates are already in a common Unreal-space frame, in centimeters.
    Named numeric attributes only are supported in this first preflight slice.
    """
    options = _object(settings, _OPTIONS, {"search_distance"}, "settings")
    start, goal = _endpoint(start, "start"), _endpoint(goal, "goal")
    mode = options.get("cost_function_mode", "DISTANCE")
    if mode not in _MODES:
        raise PathfindingValidationError("cost_function_mode must be DISTANCE, FITNESS_SCORE or COST_MULTIPLIER")
    cost_attribute = options.get("cost_attribute")
    if mode != "DISTANCE":
        cost_attribute = _attribute(cost_attribute, "cost_attribute")
    elif "cost_attribute" in options:
        raise PathfindingValidationError("cost_attribute is not used by DISTANCE; omit it")

    if not isinstance(point_cloud, list) or len(point_cloud) > MAX_POINTS:
        raise PathfindingValidationError(f"point_cloud must be an array with at most {MAX_POINTS} points")
    warnings = []
    clamped_costs = 0
    for index, point in enumerate(point_cloud):
        point = _object(point, {"position", "attributes"}, {"position"}, f"point_cloud[{index}]")
        _vector(point["position"], f"point_cloud[{index}].position")
        attributes = point.get("attributes", {})
        if not isinstance(attributes, dict) or len(attributes) > 16:
            raise PathfindingValidationError("Each point supports at most 16 named numeric attributes")
        names = set()
        for key, value in attributes.items():
            _attribute(key, "point attribute")
            if key.casefold() in names:
                raise PathfindingValidationError(
                    "Point attribute names must be distinct ignoring case (Unreal Name semantics)"
                )
            names.add(key.casefold())
            _number(value, f"point_cloud[{index}].attributes.{key}", -1e12, 1e12)
        if cost_attribute is not None:
            # Unreal Name selectors are case-insensitive; JSON keys are not.
            matches = [value for key, value in attributes.items() if key.casefold() == cost_attribute.casefold()]
            if not matches:
                raise PathfindingValidationError(f"point_cloud[{index}] is missing cost attribute {cost_attribute}")
            cost = _number(matches[0], "cost attribute", 0, 1 if mode == "FITNESS_SCORE" else 1e6)
            clamped_costs += mode == "COST_MULTIPLIER" and cost < 1

    normalized = {
        "search_distance": _number(options["search_distance"], "search_distance", 0, 1e9),
        "cost_function_mode": mode,
        "heuristic_weight": _number(options.get("heuristic_weight", 1), "heuristic_weight", 0, 100),
        "maximum_fitness_penalty_factor": _number(
            options.get("maximum_fitness_penalty_factor", 1), "maximum_fitness_penalty_factor", 0, 1e6
        ),
        # Collision constraints need a separately qualified world/trace contract.
        "use_path_traces": False,
    }
    if normalized["search_distance"] == 0:
        raise PathfindingValidationError("search_distance must be greater than zero")
    for key, default in (
        ("accept_partial_path", False),
        ("copy_originating_points", True),
        ("output_as_spline", False),
    ):
        value = options.get(key, default)
        if not isinstance(value, bool):
            raise PathfindingValidationError(f"{key} must be boolean")
        normalized[key] = value
    seed = options.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int) or not -(2**31) <= seed < 2**31:
        raise PathfindingValidationError("seed must be a signed 32-bit integer")
    normalized["seed"] = seed
    if cost_attribute is not None:
        normalized["cost_attribute"] = cost_attribute
    if "spline_mode" in options:
        if not normalized["output_as_spline"] or options["spline_mode"] not in ("CURVE", "LINEAR"):
            raise PathfindingValidationError("spline_mode requires output_as_spline and must be CURVE or LINEAR")
        normalized["spline_mode"] = options["spline_mode"]
    if "goal_mapping_mode" in options:
        value = options["goal_mapping_mode"]
        if not isinstance(value, str) or not _ENUM.fullmatch(value):
            raise PathfindingValidationError("goal_mapping_mode must be an exact uppercase host enum member")
        if "attribute" not in start or "attribute" not in goal:
            raise PathfindingValidationError("goal_mapping_mode requires attribute-driven start and goal inputs")
        normalized["goal_mapping_mode"] = value
    if not point_cloud:
        warnings.append("The point cloud is empty; configuration validation does not establish a path result.")
    if clamped_costs:
        warnings.append(f"Native COST_MULTIPLIER clamps {clamped_costs} supplied costs below 1 to 1.")
    if normalized["heuristic_weight"] > 1:
        warnings.append("A heuristic weight above 1 may trade path optimality for speed.")
    return {
        "settings": normalized,
        "start": start,
        "goal": goal,
        "point_count": len(point_cloud),
        "warnings": warnings,
    }


def _error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def _get(obj: Any, name: str) -> Any:
    try:
        return obj.get_editor_property(name)
    except Exception as exc:
        raise PathfindingHostError(f"Cannot read native property {name}: {_error(exc)}") from exc


def _transient(obj: Any) -> None:
    try:
        path = obj.get_outermost().get_path_name()
    except Exception as exc:
        raise PathfindingHostError(f"Cannot verify transient ownership: {_error(exc)}") from exc
    if path != "/Engine/Transient":
        raise PathfindingHostError("Refusing settings writes outside /Engine/Transient")


def _enum(host: Any, type_name: str, member: str) -> Any:
    enum_type = getattr(host, type_name, None)
    value = getattr(enum_type, member, None)
    if not isinstance(enum_type, type) or not isinstance(value, enum_type):
        raise PathfindingHostError(f"Native enum member {type_name}.{member} is not exposed")
    return value


def _selector(host: Any, name: str) -> Any:
    try:
        selector = host.PCGAttributePropertyInputSelector()
        changed = selector.set_attribute_name(name)
        # A false return can mean the selection did not change; readback decides.
        if changed is not None and not isinstance(changed, bool):
            raise PathfindingHostError("Unexpected native selector setter result")
        if str(selector.get_attribute_name()).casefold() != name.casefold():
            raise PathfindingHostError("Native named-attribute selector readback differs")
        return selector
    except PathfindingHostError:
        raise
    except Exception as exc:
        raise PathfindingHostError(f"Cannot configure native attribute selector: {_error(exc)}") from exc


def _readback(settings: Any, name: str, expected: Any) -> Any:
    value = _get(settings, name)
    if name in ("start", "goal"):
        value = [float(value.x), float(value.y), float(value.z)]
        if not all(math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-6) for a, b in zip(value, expected)):
            raise PathfindingHostError(f"Native {name} vector readback differs")
    elif name.endswith("_attribute"):
        value = str(value.get_attribute_name())
        if value.casefold() != expected.casefold():
            raise PathfindingHostError(f"Native {name} selector readback differs")
    elif name.endswith("_mode"):
        # Compare the actual enum value, not potentially version-dependent repr.
        if value != expected[1]:
            raise PathfindingHostError(f"Native {name} enum readback differs")
        value = expected[0]
    elif isinstance(expected, bool):
        if not isinstance(value, bool) or value != expected:
            raise PathfindingHostError(f"Native {name} boolean readback differs")
    elif isinstance(expected, (int, float)) and (
        isinstance(value, bool) or not isinstance(value, (int, float)) or value != expected
    ):
        raise PathfindingHostError(f"Native {name} numeric readback differs")
    elif value != expected:
        raise PathfindingHostError(f"Native {name} readback differs")
    return value


def _pins(node: Any, name: str) -> list[dict]:
    pins = _get(node, name)
    if len(pins) > MAX_PINS:
        raise PathfindingHostError(f"Native {name} exceeds the {MAX_PINS}-pin preflight bound")
    result = []
    for pin in pins:
        properties = _get(pin, "properties")
        multiple_data = _get(properties, "allow_multiple_data")
        multiple_connections = _get(properties, "allow_multiple_connections")
        if not isinstance(multiple_data, bool) or not isinstance(multiple_connections, bool):
            raise PathfindingHostError("Native pin multiplicity fields are not boolean")
        result.append(
            {
                "label": str(_get(properties, "label"))[:128],
                "allowed_types": str(_get(properties, "allowed_types"))[:160],
                "allow_multiple_data": multiple_data,
                "allow_multiple_connections": multiple_connections,
            }
        )
    return result


def _goal_mapping_observation(host: Any, settings: Any) -> dict:
    """Expose optional host enum spellings without inventing version gates."""
    result = {"property_readable": False, "enum_members": [], "enum_members_truncated": False}
    try:
        _get(settings, "goal_mapping_mode")
        result["property_readable"] = True
        enum_type = getattr(host, "PCGPathfindingGoalMappingMode", None)
        if isinstance(enum_type, type):
            for name in sorted(dir(enum_type)):
                if _ENUM.fullmatch(name) and isinstance(getattr(enum_type, name), enum_type):
                    if len(result["enum_members"]) == 64:
                        result["enum_members_truncated"] = True
                        break
                    result["enum_members"].append(name)
    except Exception as exc:
        result["observation_error"] = _error(exc)
    return result


def preflight_pathfinding(host: Any, point_cloud: Any, start: Any, goal: Any, settings: Any) -> dict:
    """Exercise transient settings/property readback, never generation or saving.

    Runtime presence and native property checks are authoritative, not a version
    comparison. JSON point/endpoint descriptors are not materialized as PCGData.
    """
    request = validate_pathfinding_request(point_cloud, start, goal, settings)
    values = dict(request["settings"])
    for side in ("start", "goal"):
        endpoint = request[side]
        values[f"{side}_locations_as_input"] = "attribute" in endpoint
        if "attribute" in endpoint:
            values[f"{side}_location_attribute"] = endpoint["attribute"]
        else:
            values[side] = endpoint["location"]
    try:
        native_settings = host.PCGPathfindingSettings()
        _transient(native_settings)
        # Require every property before any write, including optional fields.
        for name in values:
            _get(native_settings, name)
        converted, expected = {}, {}
        enum_types = {
            "cost_function_mode": "PCGPathfindingCostFunctionMode",
            "spline_mode": "PCGPathfindingSplineMode",
            "goal_mapping_mode": "PCGPathfindingGoalMappingMode",
        }
        for name, value in values.items():
            expected[name] = value
            if name in enum_types:
                converted[name] = _enum(host, enum_types[name], value)
                expected[name] = (value, converted[name])
            elif name.endswith("_attribute"):
                converted[name] = _selector(host, value)
            elif name in ("start", "goal"):
                converted[name] = host.Vector(*value)
            else:
                converted[name] = value
        for name, value in converted.items():
            native_settings.set_editor_property(name, value)
        for name, value in expected.items():
            _readback(native_settings, name, value)

        graph = host.PCGGraph()
        _transient(graph)
        # Copy configured settings so the new node builds pins for this exact
        # endpoint/output mode, not stale pins from an unconfigured default node.
        created = graph.add_node_copy(native_settings)
        if not isinstance(created, tuple) or len(created) != 2:
            raise PathfindingHostError("PCGGraph.add_node_copy returned an unsupported result shape")
        node, copied = created
        _transient(node)
        _transient(copied)
        if node.get_settings() != copied:
            raise PathfindingHostError("Created node does not hold the returned native settings")
        readback = {name: _readback(copied, name, value) for name, value in expected.items()}
        pins = {name: _pins(node, name) for name in ("input_pins", "output_pins")}
        if not pins["input_pins"] or not pins["output_pins"]:
            raise PathfindingHostError("Created native Pathfinding node has no inspectable input/output pins")
    except PathfindingHostError:
        raise
    except Exception as exc:
        raise PathfindingHostError(f"Native Pathfinding preflight failed: {_error(exc)}") from exc
    try:
        engine_version = str(host.SystemLibrary.get_engine_version())[:256]
    except Exception:
        engine_version = None
    return {
        "status": "preflight_ready",
        "configuration_verified": True,
        "verification_scope": "transient native property and pin readback only",
        "engine_version": engine_version,
        "version_used_as_gate": False,
        "settings_readback": readback,
        "optional_goal_mapping": _goal_mapping_observation(host, copied),
        **pins,
        "input_summary": {
            "point_count": request["point_count"],
            "start_count": len(request["start"].get("values", [None])),
            "goal_count": len(request["goal"].get("values", [None])),
            "coordinate_unit": "centimeters",
            "input_data_materialized": False,
        },
        "warnings": request["warnings"],
        "execution_verified": False,
        "generation_started": False,
        "path_result": {"status": "not_executed", "complete": None, "partial": None, "reachable": None},
        "persistent_assets_modified": False,
        "saved": False,
    }
