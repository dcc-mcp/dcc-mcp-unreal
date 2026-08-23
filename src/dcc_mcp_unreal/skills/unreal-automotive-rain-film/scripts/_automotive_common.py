"""Shared helpers for the Automotive Configurator rain-film workflow."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_error

SOURCE_LEVEL = "/Game/CarConfigurator/CarConfigurator_Main"
AUDI_BLUEPRINT = "/Game/CarConfigurator/Car/Blueprints/BP_AudiA5"
LOOKDEV_LEVEL = "/Game/AutomotiveRainFilm/Maps/Audi_Rain_Film"
SEQUENCE_PATH = "/Game/AutomotiveRainFilm/Cinematics/LS_Audi_Rain_Film"
HDRI_PATH = "/Game/References/ProductConfigurator/ART/Background/HDRI/ENV_Neutral_WarmCold.ENV_Neutral_WarmCold"
GENERATED_TAG = "AutomotiveRainFilmGenerated"


def set_property(obj, name: str, value) -> bool:
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception:
        return False


def find_actor(unreal, actor_name: str):
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in subsystem.get_all_level_actors():
        if actor.get_name() == actor_name or actor.get_actor_label() == actor_name:
            return actor
    return None


def actor_box(actor):
    try:
        box = actor.get_components_bounding_box(True, False)
        return box.min, box.max
    except Exception:
        pass
    try:
        import unreal

        minimum = None
        maximum = None
        for component in actor.get_components_by_class(unreal.PrimitiveComponent):
            bounds = component.get_editor_property("bounds")
            origin = bounds.origin
            extent = bounds.box_extent
            component_min = unreal.Vector(origin.x - extent.x, origin.y - extent.y, origin.z - extent.z)
            component_max = unreal.Vector(origin.x + extent.x, origin.y + extent.y, origin.z + extent.z)
            if minimum is None:
                minimum = component_min
                maximum = component_max
                continue
            minimum = unreal.Vector(
                min(minimum.x, component_min.x),
                min(minimum.y, component_min.y),
                min(minimum.z, component_min.z),
            )
            maximum = unreal.Vector(
                max(maximum.x, component_max.x),
                max(maximum.y, component_max.y),
                max(maximum.z, component_max.z),
            )
        return minimum, maximum
    except Exception:
        return None, None


def mesh_metrics(unreal, mesh) -> tuple[int | None, int | None]:
    vertices = None
    triangles = None
    try:
        vertices = int(mesh.get_num_vertices(0))
    except Exception:
        pass
    library = getattr(unreal, "EditorStaticMeshLibrary", None)
    if library is not None:
        for name in ("get_number_verts", "get_number_vertices"):
            if vertices is None and hasattr(library, name):
                try:
                    vertices = int(getattr(library, name)(mesh, 0))
                except Exception:
                    pass
        if hasattr(library, "get_number_triangles"):
            try:
                triangles = int(library.get_number_triangles(mesh, 0))
            except Exception:
                pass
    return vertices, triangles


def audit_actor(unreal, actor) -> dict:
    component_rows = []
    unique_meshes = set()
    unique_materials = set()
    total_vertices = 0
    total_triangles = 0
    measured_vertices = 0
    measured_triangles = 0
    components = actor.get_components_by_class(unreal.StaticMeshComponent)
    for component in components:
        mesh = component.get_editor_property("static_mesh")
        if mesh is None:
            continue
        mesh_path = mesh.get_path_name()
        unique_meshes.add(mesh_path)
        vertices, triangles = mesh_metrics(unreal, mesh)
        if vertices is not None:
            total_vertices += vertices
            measured_vertices += 1
        if triangles is not None:
            total_triangles += triangles
            measured_triangles += 1
        materials = []
        for index in range(component.get_num_materials()):
            material = component.get_material(index)
            if material is not None:
                path = material.get_path_name()
                materials.append(path)
                unique_materials.add(path)
        component_rows.append(
            {
                "component": component.get_name(),
                "mesh": mesh_path,
                "vertices_lod0": vertices,
                "triangles_lod0": triangles,
                "materials": materials,
            }
        )

    minimum, maximum = actor_box(actor)
    component_rows.sort(key=lambda row: row["vertices_lod0"] or -1, reverse=True)
    location = actor.get_actor_location()
    rotation = actor.get_actor_rotation()
    scale = actor.get_actor_scale3d()
    return {
        "actor_name": actor.get_name(),
        "actor_class": actor.get_class().get_path_name(),
        "transform": {
            "location": [location.x, location.y, location.z],
            "rotation": [rotation.roll, rotation.pitch, rotation.yaw],
            "scale": [scale.x, scale.y, scale.z],
        },
        "bounds": None
        if minimum is None
        else {
            "min": [minimum.x, minimum.y, minimum.z],
            "max": [maximum.x, maximum.y, maximum.z],
            "size": [maximum.x - minimum.x, maximum.y - minimum.y, maximum.z - minimum.z],
            "ground_contact_z": minimum.z,
        },
        "static_mesh_component_count": len(component_rows),
        "unique_static_mesh_count": len(unique_meshes),
        "unique_material_count": len(unique_materials),
        "lod0_vertices_sum": total_vertices,
        "lod0_triangles_sum": total_triangles,
        "measured_vertex_components": measured_vertices,
        "measured_triangle_components": measured_triangles,
        "top_components": component_rows[:30],
        "automotive_materials_preserved": True,
    }


def dispatch_or_error(function, *args, timeout_hint_secs: int = 120, required_capability: str | None = None):
    if required_capability is not None:
        import unreal
        from dcc_mcp_unreal.plugin_preflight import require_plugins

        preflight_error = require_plugins(unreal, required_capability)
        if preflight_error is not None:
            return preflight_error

    from dcc_mcp_unreal import server as server_module

    server = server_module._server_instance
    if server is None:
        return skill_error(
            "The Unreal DCC-MCP server is not running",
            "No server instance is available for main-thread dispatch.",
        )
    return server._main_thread_dispatcher.dispatch_callable(
        function,
        *args,
        affinity="main",
        timeout_hint_secs=timeout_hint_secs,
    )
