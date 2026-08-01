"""Small compatibility helpers for deterministic Unreal asset imports."""

from __future__ import annotations


def configure_alembic_geometry_cache_options(unreal_module):
    """Create explicit Alembic Geometry Cache options."""
    options = unreal_module.AbcImportSettings()
    options.set_editor_property("import_type", unreal_module.AlembicImportType.GEOMETRY_CACHE)
    return options


def configure_fbx_options(
    unreal_module,
    *,
    combine_meshes: bool,
    import_materials: bool,
    import_textures: bool,
    import_as_skeletal: bool = False,
    import_animations: bool = True,
):
    """Create explicit static or skeletal FBX options across UE versions."""
    options = unreal_module.FbxImportUI()
    options.set_editor_property("import_mesh", True)
    options.set_editor_property("import_as_skeletal", import_as_skeletal)
    options.set_editor_property(
        "mesh_type_to_import",
        (
            unreal_module.FBXImportType.FBXIT_SKELETAL_MESH
            if import_as_skeletal
            else unreal_module.FBXImportType.FBXIT_STATIC_MESH
        ),
    )
    options.set_editor_property("import_materials", import_materials)
    options.set_editor_property("import_textures", import_textures)
    options.set_editor_property("import_animations", import_as_skeletal and import_animations)
    if not import_as_skeletal:
        static_mesh_data = options.get_editor_property("static_mesh_import_data")
        static_mesh_data.set_editor_property("combine_meshes", combine_meshes)
    return options


def primary_object_path(
    imported_paths: list[str],
    asset_name: str,
    *,
    import_as_skeletal: bool = False,
) -> str:
    """Prefer the imported mesh over FBX sidecar assets."""
    expected_leaf = asset_name.casefold()
    for object_path in imported_paths:
        leaf = object_path.rsplit("/", 1)[-1].split(".", 1)[0]
        if leaf.casefold() == expected_leaf:
            return object_path
    if import_as_skeletal:
        sidecar_suffixes = ("_skeleton", "_physicsasset", "_anim")
        for object_path in imported_paths:
            leaf = object_path.rsplit("/", 1)[-1].split(".", 1)[0].casefold()
            if leaf.startswith(expected_leaf) and not leaf.endswith(sidecar_suffixes):
                return object_path
    return imported_paths[0]
