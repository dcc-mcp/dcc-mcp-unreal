"""Read one DynamicMesh vertex's native skin weights."""

from _dynamic_mesh_weights import get_vertex_bone_weights as _read_weights
from dcc_mcp_core.skill import skill_entry


@skill_entry
def get_vertex_bone_weights(mesh_path: str = "", vertex_id: int = 0, profile_name=None, **kwargs) -> dict:
    return _read_weights(mesh_path=mesh_path, vertex_id=vertex_id, profile_name=profile_name)
