"""Capability-gated contracts for Unreal procedural workflows.

The newer Unreal features covered here have uneven Python exposure across
engine versions and project plugins. This module keeps discovery read-only
and validates mutation requests before a skill touches a host object.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping


class ProceduralWorkflowError(ValueError):
    """Raised when a procedural workflow request is ambiguous or unsafe."""


_VERSION = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")
_FEATURES = {
    "pcg_manual_overrides": {"plugins": ("PCG",), "classes": ("PCGGraph",), "minimum_engine": (5, 8)},
    "procedural_vegetation": {
        "plugins": ("ProceduralVegetationEditor",),
        "classes": ("ProceduralVegetation", "ProceduralVegetationGraph"),
        "minimum_engine": (5, 7),
    },
    "nanite_foliage": {
        "plugins": ("NaniteAssemblyEditorUtils",),
        "classes": ("NaniteAssemblyStaticMeshBuilder",),
        "minimum_engine": (5, 8),
    },
    "mesh_terrain": {
        "plugins": ("MeshTerrainMode", "MeshPartition"),
        "classes": ("MeshPartitionDefinition",),
        "minimum_engine": (5, 8),
    },
    "megalights": {"plugins": (), "classes": (), "minimum_engine": (5, 8)},
    "substrate": {
        "plugins": (),
        "classes": ("MaterialExpressionSubstrateSlabBSDF",),
        "minimum_engine": (5, 7),
    },
}

_VALID_FEATURES = frozenset(_FEATURES)
_EXPORT_POLICIES = frozenset({"append", "replace", "ignore"})
_RHI_NAMES = frozenset({"dx11", "dx12", "vulkan", "metal", "unknown"})


def _version(value: Any, field: str = "engine_version") -> tuple[int, int]:
    if not isinstance(value, str):
        raise ProceduralWorkflowError(f"{field} must be a version string")
    match = _VERSION.match(value.strip())
    if match is None:
        raise ProceduralWorkflowError(f"{field} must start with major.minor")
    return int(match.group(1)), int(match.group(2))


def _at_least(value: tuple[int, int], minimum: tuple[int, int]) -> bool:
    return value >= minimum


def _finite_number(value: Any, field: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ProceduralWorkflowError(f"{field} must be finite")
    result = float(value)
    if result < minimum:
        raise ProceduralWorkflowError(f"{field} must be at least {minimum}")
    return result


def _package_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"/Game(?:/[A-Za-z0-9_]+)+", value):
        raise ProceduralWorkflowError(f"{field} must be a /Game package path")
    return value


def _engine_from_host(host: Any) -> str | None:
    system = getattr(host, "SystemLibrary", None)
    method = getattr(system, "get_engine_version", None)
    if not callable(method):
        return None
    try:
        value = method()
    except Exception:
        return None
    return value[:128] if isinstance(value, str) and value else None


def _enabled_plugins(host: Any) -> set[str]:
    library = getattr(host, "PluginBlueprintLibrary", None)
    for name in ("get_enabled_plugin_names", "get_enabled_plugins"):
        method = getattr(library, name, None)
        if callable(method):
            try:
                return {str(value) for value in method()}
            except Exception:
                return set()
    return set()


def _class_available(host: Any, name: str) -> bool:
    value = getattr(host, name, None)
    return isinstance(value, type) or callable(value)


def inspect_capabilities(host: Any) -> dict[str, Any]:
    """Return read-only, host-observed support for every tracked feature."""

    engine = _engine_from_host(host)
    parsed = None
    if engine:
        try:
            parsed = _version(engine)
        except ProceduralWorkflowError:
            parsed = None
    plugins = _enabled_plugins(host)
    rows: dict[str, Any] = {}
    for feature, spec in _FEATURES.items():
        required_plugins = list(spec["plugins"])
        required_classes = list(spec["classes"])
        missing_plugins = [name for name in required_plugins if name not in plugins]
        missing_classes = [name for name in required_classes if not _class_available(host, name)]
        engine_supported = parsed is None or _at_least(parsed, spec["minimum_engine"])
        if not engine_supported:
            status = "unsupported_engine"
        elif missing_plugins or missing_classes:
            status = "unavailable"
        else:
            status = "available"
        rows[feature] = {
            "status": status,
            "minimum_engine": f"{spec['minimum_engine'][0]}.{spec['minimum_engine'][1]}",
            "engine_version": engine,
            "required_plugins": required_plugins,
            "enabled_plugins_observed": sorted(plugins),
            "missing_plugins": missing_plugins,
            "required_classes": required_classes,
            "missing_classes": missing_classes,
            "execution_verified": False,
        }
    return {
        "schema": "dcc-mcp-unreal.procedural-capabilities.v1",
        "engine_version": engine,
        "capabilities": rows,
        "observation": "read_only_host_reflection_and_enabled_plugin_names",
    }


def _owned_window(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProceduralWorkflowError("owned_window evidence is required")
    required = {"provider", "runtime_version", "target_pid", "hwnd"}
    if set(value) != required:
        raise ProceduralWorkflowError("owned_window requires provider, runtime_version, target_pid and hwnd")
    if value["provider"] != "dcc-cua":
        raise ProceduralWorkflowError("owned_window.provider must be dcc-cua")
    if not isinstance(value["runtime_version"], str) or not value["runtime_version"].strip():
        raise ProceduralWorkflowError("owned_window.runtime_version is required")
    for field in ("target_pid", "hwnd"):
        if isinstance(value[field], bool) or not isinstance(value[field], int) or value[field] <= 0:
            raise ProceduralWorkflowError(f"owned_window.{field} must be a positive integer")
    return dict(value)


def _validate_common(feature: str, operation: str, request: Mapping[str, Any]) -> dict[str, Any]:
    if feature not in _VALID_FEATURES:
        raise ProceduralWorkflowError(f"unsupported feature: {feature}")
    if not isinstance(operation, str) or not operation:
        raise ProceduralWorkflowError("operation is required")
    if not isinstance(request, Mapping):
        raise ProceduralWorkflowError("request must be an object")
    normalized = dict(request)
    normalized["feature"] = feature
    normalized["operation"] = operation
    return normalized


def validate_request(feature: str, operation: str, request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one bounded workflow and return a mutation-ready plan.

    The result is a contract only. Native skills still need to probe the
    corresponding host API immediately before mutation and verify readback.
    """

    normalized = _validate_common(feature, operation, request)
    if feature == "pcg_manual_overrides":
        if operation not in {"select", "exclude", "restore", "apply", "cancel", "undo", "redo"}:
            raise ProceduralWorkflowError("unsupported PCG manual override operation")
        normalized["owned_window"] = _owned_window(normalized.get("owned_window"))
        scope = normalized.get("scope", "persistent")
        if scope not in {"persistent", "temporary"}:
            raise ProceduralWorkflowError("scope must be persistent or temporary")
        if not isinstance(normalized.get("expected_revision"), str) or not normalized["expected_revision"]:
            raise ProceduralWorkflowError("expected_revision is required for optimistic mutation")
        normalized["scope"] = scope
        normalized["mutation_requires_post_state"] = True
        normalized["routing"] = "dcc-cua"
    elif feature == "procedural_vegetation":
        if operation not in {"author", "export"}:
            raise ProceduralWorkflowError("procedural vegetation supports author or export")
        target_version = _version(normalized.get("engine_version"))
        source_version = normalized.get("source_engine_version", normalized["engine_version"])
        if _version(source_version, "source_engine_version") != target_version:
            raise ProceduralWorkflowError("PVE assets cannot be implicitly migrated across engine versions")
        normalized["source_engine_version"] = source_version
        normalized["destination_path"] = _package_path(normalized.get("destination_path"), "destination_path")
        policy = normalized.get("export_policy", "append")
        if policy not in _EXPORT_POLICIES:
            raise ProceduralWorkflowError("export_policy must be append, replace or ignore")
        normalized["export_policy"] = policy
        normalized["collision_policy"] = normalized.get("collision_policy", "preserve")
        normalized["wind_verified"] = False
    elif feature == "nanite_foliage":
        if operation not in {"inspect", "configure", "qualify"}:
            raise ProceduralWorkflowError("unsupported Nanite Foliage operation")
        if normalized.get("ordinary_nanite") is not False:
            raise ProceduralWorkflowError("ordinary Nanite content is not a Nanite Foliage assembly")
        if normalized.get("workflow") not in {"assembly", "voxel", "skinning"}:
            raise ProceduralWorkflowError("workflow must be assembly, voxel or skinning")
        if not isinstance(normalized.get("asset_path"), str) or not normalized["asset_path"].startswith("/Game/"):
            raise ProceduralWorkflowError("asset_path must be a /Game package path")
        rhi = str(normalized.get("target_rhi", "")).casefold()
        if rhi not in _RHI_NAMES - {"unknown"}:
            raise ProceduralWorkflowError("target_rhi must be an observed supported RHI")
        normalized["target_rhi"] = rhi
        normalized["experimental"] = True
        normalized["ordinary_nanite_distinguished"] = True
    elif feature == "mesh_terrain":
        if operation not in {"inspect", "create", "edit", "build", "qualify"}:
            raise ProceduralWorkflowError("unsupported Mesh Terrain operation")
        if normalized.get("world_partition") is not True:
            raise ProceduralWorkflowError("Mesh Terrain requires an observed World Partition world")
        if normalized.get("static_mesh_substitute") is True:
            raise ProceduralWorkflowError("a generic static-mesh substitute is outside Mesh Terrain scope")
        if normalized.get("source_type") not in {"rectangle", "heightmap", "mesh"}:
            raise ProceduralWorkflowError("source_type must be rectangle, heightmap or mesh")
        build_state = normalized.get("build_state", "compiled")
        if build_state not in {"preview", "compiled"}:
            raise ProceduralWorkflowError("build_state must be preview or compiled")
        if normalized.get("pcg_write", False) and normalized.get("source_point_correspondence") is not True:
            raise ProceduralWorkflowError("PCG writes require explicit source point correspondence")
        normalized["build_state"] = build_state
        normalized["preview_only"] = build_state == "preview"
        normalized["recursive_regeneration_allowed"] = False
    elif feature == "megalights":
        if operation not in {"inspect", "configure", "qualify"}:
            raise ProceduralWorkflowError("unsupported MegaLights operation")
        version = _version(normalized.get("engine_version"))
        if not _at_least(version, (5, 8)):
            raise ProceduralWorkflowError("MegaLights qualification requires Unreal 5.8 or newer")
        if str(normalized.get("renderer", "")).casefold() != "deferred":
            raise ProceduralWorkflowError("MegaLights requires an observed deferred renderer")
        rhi = str(normalized.get("target_rhi", "")).casefold()
        if rhi not in _RHI_NAMES - {"unknown"}:
            raise ProceduralWorkflowError("target_rhi must be an observed supported RHI")
        budget = normalized.get("target_budget")
        if not isinstance(budget, Mapping):
            raise ProceduralWorkflowError("target_budget is required")
        _finite_number(budget.get("gpu_ms"), "target_budget.gpu_ms")
        _finite_number(budget.get("memory_mb"), "target_budget.memory_mb")
        normalized["restart_required"] = bool(normalized.get("restart_required", False))
        normalized["qualification_requires_measurement"] = True
    elif feature == "substrate":
        if operation not in {"inspect", "author", "convert", "qualify"}:
            raise ProceduralWorkflowError("unsupported Substrate operation")
        normalized["material_path"] = _package_path(normalized.get("material_path"), "material_path")
        if normalized.get("root") not in {"slab", "front_material"}:
            raise ProceduralWorkflowError("root must be slab or front_material")
        converting = operation == "convert"
        if converting and normalized.get("conversion_intent") is not True:
            raise ProceduralWorkflowError("conversion requires explicit conversion_intent=true")
        if converting and normalized.get("disposable_copy") is not True:
            raise ProceduralWorkflowError("conversion requires a disposable_copy")
        if converting and normalized.get("backup_required") is not True:
            raise ProceduralWorkflowError("conversion requires backup_required=true")
        normalized["legacy_preserved"] = not converting
        normalized["platform"] = str(normalized.get("platform", "desktop")).casefold()
    return {
        "schema": "dcc-mcp-unreal.procedural-workflow-plan.v1",
        "status": "validated",
        "plan": normalized,
        "mutation": operation not in {"inspect", "qualify", "cancel", "undo", "redo"},
        "execution_verified": False,
        "readback_required": operation not in {"inspect", "qualify"},
    }

