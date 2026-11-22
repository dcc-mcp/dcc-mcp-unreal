"""Apply a non-overwriting asset handoff plan with rollback on failure."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def apply_asset_handoff(plan: dict, rewrite_references: bool = True, **kwargs) -> dict:
    """Copy assets and optionally consolidate source referencers into copies."""
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
        if not isinstance(rewrite_references, bool):
            raise AssetHandoffError("rewrite_references must be boolean")
        rewrites = plan.get("reference_rewrites", copy_items)
        if not isinstance(rewrites, list) or any(
            not isinstance(item, dict) or set(item) != {"source", "destination"} for item in rewrites
        ):
            raise AssetHandoffError("reference_rewrites must contain source and destination entries")
    except AssetHandoffError as exc:
        return skill_error("Invalid asset handoff apply request", str(exc), error_kind="invalid_input")

    created: list[str] = []
    try:
        import unreal  # noqa: PLC0415

        for item in copy_items:
            destination = str(item["destination"])
            if unreal.EditorAssetLibrary.does_asset_exist(destination):
                raise RuntimeError(f"Refusing to overwrite existing asset: {destination}")
        if rewrite_references and not callable(getattr(unreal.EditorAssetLibrary, "consolidate_assets", None)):
            raise RuntimeError("Unreal host does not expose consolidate_assets for reference rewriting")
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
        rewritten = []
        if rewrite_references:
            for item in rewrites:
                source = str(item["source"])
                destination = str(item["destination"])
                source_asset = unreal.EditorAssetLibrary.load_asset(source)
                destination_asset = unreal.EditorAssetLibrary.load_asset(destination)
                if source_asset is None or destination_asset is None:
                    raise RuntimeError(f"Cannot load source and destination for reference rewrite: {source} -> {destination}")
                if not unreal.EditorAssetLibrary.consolidate_assets(destination_asset, [source_asset]):
                    raise RuntimeError(f"Unreal failed to rewrite referencers: {source} -> {destination}")
                rewritten.append({"source": source, "destination": destination})
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
        reference_rewrite="performed" if rewrite_references else "skipped_by_request",
        rewritten_references=rewritten if rewrite_references else [],
        verification_required=True,
        assets_mutated=True,
        next_step="Call verify_asset_handoff with fresh Asset Registry evidence.",
    )
