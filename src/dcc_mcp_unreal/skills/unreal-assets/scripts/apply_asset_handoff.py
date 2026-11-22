"""Apply a non-overwriting asset handoff plan with rollback on failure."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def apply_asset_handoff(plan: dict, **kwargs) -> dict:
    """Copy planned assets without claiming reference rewrites or verification."""
    from dcc_mcp_unreal.asset_handoff import AssetHandoffError  # noqa: PLC0415

    if kwargs:
        return skill_error("Invalid asset handoff apply request", "Unknown arguments", error_kind="invalid_input")
    if not isinstance(plan, dict):
        return skill_error("Invalid asset handoff apply request", "plan must be an object", error_kind="invalid_input")
    try:
        if plan.get("schema") != "dcc-mcp-unreal.asset-handoff-plan.v1" or plan.get("status") != "planned":
            raise AssetHandoffError("plan is not a compatible asset-handoff plan")
        copy_items = plan.get("copy")
        if not isinstance(copy_items, list) or not copy_items:
            raise AssetHandoffError("plan has no assets to copy")
        if plan.get("overwrite_allowed") is not False:
            raise AssetHandoffError("apply requires overwrite_allowed=false")
        for item in copy_items:
            if not isinstance(item, dict) or set(item) != {"source", "destination"}:
                raise AssetHandoffError("plan copy entries require source and destination")
    except AssetHandoffError as exc:
        return skill_error("Invalid asset handoff apply request", str(exc), error_kind="invalid_input")

    created: list[str] = []
    try:
        import unreal  # noqa: PLC0415

        for item in copy_items:
            destination = str(item["destination"])
            if unreal.EditorAssetLibrary.does_asset_exist(destination):
                raise RuntimeError(f"Refusing to overwrite existing asset: {destination}")
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        for item in copy_items:
            source = str(item["source"])
            destination = str(item["destination"])
            source_asset = unreal.EditorAssetLibrary.load_asset(source)
            if source_asset is None:
                raise RuntimeError(f"Source asset is unavailable: {source}")
            package_path, asset_name = destination.rsplit("/", 1)
            copied = asset_tools.duplicate_asset(asset_name, package_path, source_asset)
            if copied is None:
                raise RuntimeError(f"AssetTools failed to duplicate {source} to {destination}")
            if not unreal.EditorAssetLibrary.save_asset(destination, only_if_is_dirty=False):
                raise RuntimeError(f"Unreal failed to save duplicated asset: {destination}")
            created.append(destination)
    except ImportError:
        return skill_error(
            "Unreal Python API is unavailable",
            "A running Unreal Editor is required for apply",
            error_kind="host_unavailable",
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        try:
            for path in reversed(created):
                unreal.EditorAssetLibrary.delete_asset(path)
        except Exception as rollback_error:
            return skill_error(
                "Asset handoff apply failed and rollback was incomplete",
                f"{exc}; rollback error: {rollback_error}",
                error_kind="rollback_incomplete",
                created_assets=created,
            )
        return skill_error(
            "Asset handoff apply failed",
            str(exc),
            error_kind="apply_failed",
            rollback_completed=True,
            created_assets=[],
        )

    return skill_success(
        "Applied the non-overwriting asset copy plan.",
        status="applied_unverified",
        created_assets=created,
        reference_rewrite="not_performed",
        verification_required=True,
        assets_mutated=True,
        next_step="Call verify_asset_handoff with fresh Asset Registry evidence.",
    )
