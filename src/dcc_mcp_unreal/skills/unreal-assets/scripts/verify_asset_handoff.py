"""Verify a localized asset handoff against fresh Asset Registry evidence."""

from __future__ import annotations

from collections import deque

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def verify_asset_handoff(plan: dict, baseline_paths: list[str] | None = None, **kwargs) -> dict:
    """Verify translated roots and report remaining source dependencies."""
    from dcc_mcp_unreal.asset_handoff import AssetHandoffError, verify_handoff  # noqa: PLC0415

    if kwargs:
        return skill_error("Invalid asset handoff verification", "Unknown arguments", error_kind="invalid_input")
    if not isinstance(plan, dict):
        return skill_error("Invalid asset handoff verification", "plan must be an object", error_kind="invalid_input")
    try:
        import unreal  # noqa: PLC0415

        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        roots = plan.get("roots", [])
        source_root = str(plan["source_root"])
        destination_root = str(plan["destination_root"])
        applied_roots = [
            destination_root + root[len(source_root) :]
            for root in roots
            if root == source_root or root.startswith(source_root + "/")
        ]
        dependencies: dict[str, list[str]] = {}
        queue = deque(applied_roots)
        options = unreal.AssetRegistryDependencyOptions()
        while queue:
            package = queue.popleft()
            if package in dependencies:
                continue
            values = sorted(
                str(value)
                for value in registry.get_dependencies(package, options)
                if not str(value).startswith("/Script/")
            )
            dependencies[package] = values
            queue.extend(value for value in values if value not in dependencies)
        result = verify_handoff(plan, observed_dependencies=dependencies, baseline=baseline_paths)
    except ImportError:
        return skill_error(
            "Unreal Python API is unavailable",
            "A running Unreal Editor is required for fresh verification",
            error_kind="host_unavailable",
        )
    except (AssetHandoffError, KeyError, RuntimeError) as exc:
        return skill_error("Asset handoff verification failed", str(exc), error_kind="invalid_or_unavailable")
    return skill_success(
        "Verified asset dependencies against fresh Asset Registry evidence.",
        verification=result,
        assets_mutated=False,
        files_copied=False,
    )
