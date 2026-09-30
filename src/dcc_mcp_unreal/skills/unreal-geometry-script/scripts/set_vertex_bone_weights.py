"""Write one DynamicMesh vertex's native skin weights with SDK readback."""

from _dynamic_mesh_weights import set_vertex_bone_weights as _write_weights
from dcc_mcp_core.skill import skill_entry


@skill_entry
def set_vertex_bone_weights(
    mesh_path: str = "", vertex_id: int = 0, bone_weights=None, profile_name=None, **kwargs
) -> dict:
    return _write_weights(
        mesh_path=mesh_path, vertex_id=vertex_id, bone_weights=bone_weights, profile_name=profile_name
    )
