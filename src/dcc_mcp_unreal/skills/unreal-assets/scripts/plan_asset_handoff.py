"""Create a dependency-aware, read-only asset handoff plan."""

from __future__ import annotations

from collections import deque

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _package(value: str) -> str:
    return value.split(".", 1)[0]


@skill_entry
def plan_asset_handoff(
    asset_paths: list[str],
    source_root: str,
    destination_root: str,
    baseline_paths: list[str] | None = None,
    **kwargs,
) -> dict:
    """Plan localization from a fresh Asset Registry dependency observation."""
    from dcc_mcp_unreal.asset_handoff import AssetHandoffError, plan_handoff  # noqa: PLC0415

    if kwargs:
        return skill_error("Invalid asset handoff request", "Unknown arguments", error_kind="invalid_input")
    try:
        if not asset_paths:
            raise AssetHandoffError("asset_paths must contain at least one package")
        roots = [_package(path) for path in asset_paths]
        import unreal  # noqa: PLC0415

        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        dependencies: dict[str, list[str]] = {}
        queue = deque(roots)
        options = unreal.AssetRegistryDependencyOptions()
        while queue:
            package = queue.popleft()
            if package in dependencies:
                continue
            values = [str(value) for value in registry.get_dependencies(package, options)]
            values = sorted(value for value in values if not value.startswith("/Script/"))
            dependencies[package] = values
            queue.extend(value for value in values if value not in dependencies)
        result = plan_handoff(
            roots,
            dependencies,
            source_root=source_root,
            destination_root=destination_root,
            baseline=baseline_paths,
        )
    except ImportError:
        return skill_error(
            "Unreal Python API is unavailable",
            "A running Unreal Editor is required for a fresh Asset Registry observation",
            error_kind="host_unavailable",
        )
    except (AssetHandoffError, RuntimeError) as exc:
        return skill_error("Asset handoff planning failed", str(exc), error_kind="invalid_or_unavailable")
    return skill_success(
        "Created a read-only asset handoff plan from fresh Asset Registry dependencies.",
        plan=result,
        dependency_observation="fresh_asset_registry_direct_dependencies",
        assets_mutated=False,
        files_copied=False,
    )
