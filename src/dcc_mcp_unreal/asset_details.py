"""Read-only reflected asset evidence; unavailable values are never synthetic zeroes."""

from __future__ import annotations


def observe(source, read):
    """Keep a failed individual observation distinct from an observed empty value."""
    try:
        return {"status": "observed", "source": source, "value": read()}
    except Exception as exc:
        return {"status": "unavailable", "source": source, "reason": str(exc)}


def _count(value):
    if value < 0:
        raise ValueError("Unreal returned an error sentinel")
    return int(value)


def _path(obj):
    return str(obj.get_path_name()) if obj is not None else None


def _vector(value):
    return {axis: float(getattr(value, axis)) for axis in ("x", "y", "z")}


def _material(unreal, material, ancestors=()):
    if material is None:
        return {"object_path": None, "status": "unassigned"}
    result = {"object_path": _path(material), "class": material.get_class().get_name()}
    if result["object_path"] in ancestors or len(ancestors) >= 8:
        return {**result, "status": "unavailable", "reason": "Parent cycle or depth limit"}
    for name in ("parent", "two_sided", "blend_mode", "opacity_mask_clip_value"):

        def read(name=name):
            value = material.get_editor_property(name)
            return _path(value) if name == "parent" else (str(value) if name == "blend_mode" else value)

        result[name] = observe("get_editor_property." + name, read)
    # Explicitly scoped to global parameters: layer/association identities are not collapsed.
    library = unreal.MaterialEditingLibrary
    if isinstance(material, unreal.MaterialInstanceConstant):
        result["parent_details"] = observe(
            "MaterialInstance.parent",
            lambda: _material(unreal, material.get_editor_property("parent"), ancestors + (_path(material),)),
        )
        for kind in ("texture", "scalar", "static_switch"):

            def parameters(kind=kind):
                names = getattr(library, "get_" + kind + "_parameter_names")(material)
                getter = getattr(library, "get_material_instance_" + kind + "_parameter_value")
                return [
                    {
                        "name": str(name),
                        "association": "GlobalParameter",
                        "value": _path(getter(material, name)) if kind == "texture" else getter(material, name),
                    }
                    for name in names
                ]

            result[kind + "_parameters"] = observe("MaterialEditingLibrary.global_" + kind, parameters)
        result["parameter_scope"] = "global_only; material layer parameters are not inspected"
        result["base_property_overrides"] = observe(
            "base_property_overrides",
            lambda: {
                name: str(material.get_editor_property("base_property_overrides").get_editor_property(name))
                for name in (
                    "override_two_sided",
                    "two_sided",
                    "override_blend_mode",
                    "blend_mode",
                    "override_opacity_mask_clip_value",
                    "opacity_mask_clip_value",
                )
            },
        )
    else:
        result["textures"] = observe(
            "MaterialEditingLibrary.get_used_textures", lambda: [_path(t) for t in library.get_used_textures(material)]
        )
    return result


def asset_details(unreal, asset, asset_class):
    """Collect bounded mesh/material metadata without saving or editing assets."""
    result = {
        "schema_version": 1,
        "package_dirty": observe(
            "EditorLoadingAndSavingUtils.get_dirty_content_packages",
            lambda: (
                _path(asset.get_outer())
                in [_path(package) for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()]
            ),
        ),
        "wind": {
            "status": "unavailable",
            "reason": "Native wind binding is not exposed by this Python contract",
            "dynamic_validation": "not_performed",
        },
    }
    if asset_class.startswith("Material"):
        result["material"] = _material(unreal, asset)
    if asset_class != "StaticMesh":
        return result
    count = observe("StaticMesh.get_num_lods", lambda: _count(asset.get_num_lods()))
    result["lod_count"] = count
    subsystem = None
    try:
        subsystem = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    except Exception:
        subsystem = getattr(unreal, "EditorStaticMeshLibrary", None)
    screens = observe(
        "StaticMeshEditorSubsystem.get_lod_screen_sizes",
        lambda: [float(v) for v in subsystem.get_lod_screen_sizes(asset)],
    )
    result["lod_screen_sizes"] = screens
    result["lods"] = []
    if count["status"] == "observed":
        for index in range(count["value"]):
            row = {"index": index}
            for field, method in (
                ("vertices", "get_num_vertices"),
                ("triangles", "get_num_triangles"),
                ("sections", "get_num_sections"),
            ):
                row[field] = observe(
                    "StaticMesh." + method, lambda method=method, index=index: _count(getattr(asset, method)(index))
                )
            if row["vertices"]["status"] == "unavailable":
                row["vertices"] = observe(
                    "StaticMeshEditorSubsystem.get_number_verts",
                    lambda index=index: _count(subsystem.get_number_verts(asset, index)),
                )
            row["section_material_slots"] = observe(
                "StaticMeshEditorSubsystem.get_lod_material_slot",
                lambda index=index: [
                    _count(subsystem.get_lod_material_slot(asset, index, section))
                    for section in range(row["sections"]["value"])
                ],
            )
            result["lods"].append(row)
    result["bounds"] = observe(
        "StaticMesh.get_bounds",
        lambda: {
            "origin": _vector(asset.get_bounds().origin),
            "extent": _vector(asset.get_bounds().box_extent),
            "sphere_radius": float(asset.get_bounds().sphere_radius),
            "units": "cm",
            "space": "mesh_local",
        },
    )
    for field, method in (
        ("simple_collision_count", "get_simple_collision_count"),
        ("convex_collision_count", "get_convex_collision_count"),
    ):
        result[field] = observe(
            "StaticMeshEditorSubsystem." + method, lambda method=method: _count(getattr(subsystem, method)(asset))
        )
    result["material_slots"] = observe(
        "StaticMesh.static_materials",
        lambda: [
            {
                "index": index,
                "slot_name": str(slot.get_editor_property("material_slot_name")),
                "material": _material(unreal, slot.get_editor_property("material_interface")),
            }
            for index, slot in enumerate(asset.get_editor_property("static_materials"))
        ],
    )
    return result
