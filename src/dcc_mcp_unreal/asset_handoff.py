"""Pure planning and verification contracts for incremental Unreal asset handoff."""

from __future__ import annotations

from collections import deque
from pathlib import PurePosixPath
from typing import Any, Mapping


class AssetHandoffError(ValueError):
    """Raised when an asset handoff request is ambiguous or unsafe."""


def _package(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or "." in value:
        raise AssetHandoffError(f"{field} must be a package path without an object suffix")
    path = PurePosixPath(value)
    if ".." in path.parts or len(path.parts) < 2:
        raise AssetHandoffError(f"{field} must be an absolute Unreal package path")
    return str(path)


def _destination(source: str, source_root: str, destination_root: str) -> str:
    source_path = PurePosixPath(source)
    source_prefix = PurePosixPath(source_root)
    if source_path != source_prefix and source_prefix not in source_path.parents:
        raise AssetHandoffError(f"asset {source} is outside source_root {source_root}")
    relative = source_path.relative_to(source_prefix)
    return str(PurePosixPath(destination_root) / relative)


def plan_handoff(
    roots: list[str],
    dependencies: Mapping[str, list[str]],
    *,
    source_root: str,
    destination_root: str,
    baseline: list[str] | None = None,
    _allow_external_roots: bool = False,
) -> dict[str, Any]:
    """Build a deterministic copy plan from a direct dependency graph.

    The graph is supplied by a fresh Asset Registry observation. This function
    never guesses dependencies, changes references, or overwrites a destination.
    """
    source_root = _package(source_root, "source_root")
    destination_root = _package(destination_root, "destination_root")
    if destination_root == source_root or destination_root.startswith(source_root + "/"):
        raise AssetHandoffError("destination_root must be outside source_root")
    normalized_roots = [_package(value, "roots[]") for value in roots]
    if not _allow_external_roots and any(
        root != source_root and not root.startswith(source_root + "/") for root in normalized_roots
    ):
        raise AssetHandoffError("roots must be inside source_root")
    normalized_graph: dict[str, list[str]] = {}
    for key, values in dependencies.items():
        package = _package(key, "dependencies key")
        if not isinstance(values, list):
            raise AssetHandoffError(f"dependencies for {package} must be a list")
        normalized_graph[package] = [_package(value, f"dependencies[{package}]") for value in values]

    baseline_set = {_package(value, "baseline[]") for value in (baseline or [])}
    visited: set[str] = set()
    missing: set[str] = set()
    queue = deque(normalized_roots)
    while queue:
        package = queue.popleft()
        if package in visited:
            continue
        visited.add(package)
        if package not in normalized_graph:
            missing.add(package)
            continue
        queue.extend(normalized_graph[package])

    plugin_packages = sorted(package for package in visited if package.startswith(source_root + "/"))
    shared_packages = sorted(package for package in visited if package in baseline_set)
    copy_packages = [package for package in plugin_packages if package not in baseline_set]
    missing_new = sorted(package for package in missing if package not in baseline_set)
    missing_existing = sorted(package for package in missing if package in baseline_set)
    return {
        "schema": "dcc-mcp-unreal.asset-handoff-plan.v1",
        "status": "planned",
        "source_root": source_root,
        "destination_root": destination_root,
        "roots": normalized_roots,
        "closure": sorted(visited),
        "copy": [
            {"source": package, "destination": _destination(package, source_root, destination_root)}
            for package in copy_packages
        ],
        "shared": shared_packages,
        "missing_dependencies": missing_new,
        "preexisting_missing_dependencies": missing_existing,
        "dependency_policy": "direct-asset-registry-closure",
        "apply_required": bool(copy_packages),
        "overwrite_allowed": False,
    }


def verify_handoff(
    plan: Mapping[str, Any],
    *,
    observed_dependencies: Mapping[str, list[str]],
    baseline: list[str] | None = None,
) -> dict[str, Any]:
    """Verify fresh dependency observations against a previously emitted plan."""
    if plan.get("schema") != "dcc-mcp-unreal.asset-handoff-plan.v1" or plan.get("status") != "planned":
        raise AssetHandoffError("plan is not a compatible asset-handoff plan")
    roots = plan.get("roots")
    if not isinstance(roots, list):
        raise AssetHandoffError("plan roots are missing")
    source_root = str(plan["source_root"])
    destination_root = str(plan["destination_root"])
    applied_roots = [_destination(root, source_root, destination_root) for root in roots]
    fresh = plan_handoff(
        applied_roots,
        observed_dependencies,
        source_root=source_root,
        destination_root=destination_root,
        baseline=baseline,
        _allow_external_roots=True,
    )
    remaining = sorted(package for package in fresh["closure"] if package.startswith(source_root + "/"))
    missing = sorted(fresh["missing_dependencies"])
    return {
        "schema": "dcc-mcp-unreal.asset-handoff-verification.v1",
        "status": "verified" if not remaining and not missing else "failed",
        "remaining_source_dependencies": remaining,
        "new_missing_dependencies": missing,
        "preexisting_missing_dependencies": fresh["preexisting_missing_dependencies"],
        "closure": fresh["closure"],
    }
