"""Create a game-ready Chaos Geometry Collection from a Static Mesh."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def create_geometry_collection(
    static_mesh_path: str = "",
    destination_path: str = "/Game/GeometryCollections",
    collection_name: str = "",
    damage_threshold: float = 1000.0,
    **kwargs,
) -> dict:
    """Convert disconnected Static Mesh islands into a clustered Chaos asset."""
    import unreal  # noqa: PLC0415

    if not static_mesh_path or not collection_name:
        return skill_error(
            "static_mesh_path and collection_name are required",
            "A source Static Mesh and an output name must be supplied",
        )
    if not destination_path.startswith("/Game") or damage_threshold <= 0:
        return skill_error(
            "Invalid Geometry Collection settings",
            "destination_path must be under /Game and damage_threshold must be greater than zero",
        )

    create = getattr(unreal.DccMcpAutomationLibrary, "create_geometry_collection_from_static_mesh", None)
    if create is None:
        return skill_error(
            "Chaos conversion is unavailable",
            "DccMcpAutomationLibrary.create_geometry_collection_from_static_mesh is missing",
            possible_solutions=["Install a DCC MCP Unreal release that includes the unreal-chaos skill."],
        )
    asset_path = create(static_mesh_path, destination_path.rstrip("/"), collection_name, float(damage_threshold))
    if not asset_path:
        return skill_error("Failed to create Geometry Collection", "Unreal conversion returned an empty asset path")

    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if asset is None or not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
        return skill_error("Failed to save Geometry Collection", f"Could not save '{asset_path}'")
    return skill_success(
        f"Created Chaos Geometry Collection '{asset_path}'",
        prompt="Spawn it with unreal_chaos__spawn_geometry_collection_actor, then run physics simulation.",
        geometry_collection_path=asset_path,
        source_static_mesh_path=static_mesh_path,
        damage_threshold=float(damage_threshold),
    )
