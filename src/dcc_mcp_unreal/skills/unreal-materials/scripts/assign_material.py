"""Bind a Material Interface to a persistent mesh/cache asset or level actor."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _is_material_interface(asset, unreal) -> bool:
    if isinstance(asset, unreal.MaterialInterface):
        return True
    get_class = getattr(asset, "get_class", None)
    asset_class = get_class() if callable(get_class) else None
    get_name = getattr(asset_class, "get_name", None)
    return callable(get_name) and get_name() in {
        "Material",
        "MaterialInstance",
        "MaterialInstanceConstant",
        "MaterialInstanceDynamic",
    }


@skill_entry
def assign_material(
    target_kind: str = "",
    target_path: str = "",
    material_path: str = "",
    slot_index: int = 0,
    **kwargs,
) -> dict:
    """Assign one material slot to a persistent asset or live actor components."""
    import unreal  # noqa: PLC0415

    if target_kind not in {"static_mesh", "geometry_cache", "actor"} or not target_path or slot_index < 0:
        return skill_error(
            "Invalid material target",
            "target_kind must be static_mesh, geometry_cache, or actor and slot_index must be non-negative",
        )
    material = unreal.EditorAssetLibrary.load_asset(material_path)
    if material is None or not _is_material_interface(material, unreal):
        return skill_error("Material not found", f"'{material_path}' is not a Material Interface")

    if target_kind == "static_mesh":
        mesh = unreal.EditorAssetLibrary.load_asset(target_path)
        if mesh is None or not isinstance(mesh, unreal.StaticMesh):
            return skill_error("Static Mesh not found", f"'{target_path}' is not a StaticMesh")
        mesh.set_material(int(slot_index), material)
        if not unreal.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False):
            return skill_error("Failed to save Static Mesh", target_path)
        applied_count = 1
    elif target_kind == "geometry_cache":
        cache = unreal.EditorAssetLibrary.load_asset(target_path)
        if cache is None or not isinstance(cache, unreal.GeometryCache):
            return skill_error("Geometry Cache not found", f"'{target_path}' is not a GeometryCache")
        materials = list(cache.get_editor_property("materials"))
        materials.extend([None] * (int(slot_index) + 1 - len(materials)))
        materials[int(slot_index)] = material
        cache.set_editor_property("materials", materials)
        if not unreal.EditorAssetLibrary.save_loaded_asset(cache, only_if_is_dirty=False):
            return skill_error("Failed to save Geometry Cache", target_path)
        applied_count = 1
    else:
        actor = next(
            (
                candidate
                for candidate in unreal.EditorLevelLibrary.get_all_level_actors()
                if candidate.get_name() == target_path or candidate.get_actor_label() == target_path
            ),
            None,
        )
        if actor is None:
            return skill_error("Actor not found", f"No level actor matches '{target_path}'")
        components = actor.get_components_by_class(unreal.PrimitiveComponent)
        for component in components:
            component.set_material(int(slot_index), material)
        if not components:
            return skill_error("Actor has no primitive components", actor.get_name())
        applied_count = len(components)

    return skill_success(
        f"Assigned '{material_path}' to {target_kind} '{target_path}'",
        target_kind=target_kind,
        target_path=target_path,
        material_path=material_path,
        slot_index=int(slot_index),
        applied_component_count=applied_count,
    )
