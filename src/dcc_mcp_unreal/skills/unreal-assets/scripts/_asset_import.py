"""Small compatibility helpers for deterministic Unreal asset imports."""

from __future__ import annotations


def configure_fbx_options(
    unreal_module,
    *,
    combine_meshes: bool,
    import_materials: bool,
    import_textures: bool,
):
    """Create explicit static-mesh FBX options across supported UE versions."""
    options = unreal_module.FbxImportUI()
    options.set_editor_property("import_mesh", True)
    options.set_editor_property("import_as_skeletal", False)
    options.set_editor_property(
        "mesh_type_to_import",
        unreal_module.FBXImportType.FBXIT_STATIC_MESH,
    )
    options.set_editor_property("import_materials", import_materials)
    options.set_editor_property("import_textures", import_textures)
    static_mesh_data = options.get_editor_property("static_mesh_import_data")
    static_mesh_data.set_editor_property("combine_meshes", combine_meshes)
    return options


def primary_object_path(imported_paths: list[str], asset_name: str) -> str:
    """Prefer the explicitly named asset over FBX sidecar materials/textures."""
    expected_leaf = asset_name.casefold()
    for object_path in imported_paths:
        leaf = object_path.rsplit("/", 1)[-1].split(".", 1)[0]
        if leaf.casefold() == expected_leaf:
            return object_path
    return imported_paths[0]
