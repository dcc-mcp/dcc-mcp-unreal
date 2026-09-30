"""Native Geometry Script skin weight access for existing DynamicMesh objects."""

from __future__ import annotations

import math

from dcc_mcp_core.skill import skill_error, skill_success


def _resolve(mesh_path, vertex_id, profile_name):
    import unreal

    if not isinstance(mesh_path, str) or not mesh_path.strip():
        raise ValueError("mesh_path must identify an existing DynamicMesh object")
    if isinstance(vertex_id, bool) or not isinstance(vertex_id, int) or vertex_id < 0:
        raise ValueError("vertex_id must be a nonnegative integer")
    if profile_name is not None and (
        not isinstance(profile_name, str)
        or not profile_name
        or profile_name.casefold() == "none"
        or any(c.isspace() for c in profile_name)
    ):
        raise ValueError("profile_name must be a nonempty name without whitespace or None")
    api = getattr(unreal, "GeometryScript_BoneWeights", None)
    queries = getattr(unreal, "GeometryScript_MeshQueries", None)
    if api is None or queries is None:
        raise ValueError("Geometry Scripting Python API is unavailable; enable the GeometryScripting plugin")
    mesh = unreal.find_object(None, mesh_path)
    if mesh is None or not isinstance(mesh, unreal.DynamicMesh):
        raise ValueError("mesh_path does not resolve to an existing DynamicMesh")
    if not queries.is_valid_vertex_id(mesh, vertex_id):
        raise ValueError(f"Vertex {vertex_id} does not exist on the DynamicMesh")
    profile = unreal.GeometryScriptBoneWeightProfile()
    if profile_name is not None:
        profile.set_editor_property("profile_name", profile_name)
    return unreal, api, mesh, profile


def _read(api, mesh, vertex_id, profile):
    _, weights, valid = api.get_vertex_bone_weights(mesh, vertex_id, profile=profile)
    if not valid:
        raise ValueError("The vertex has no bone weights in the requested profile")
    # Unreal pads native storage with zero-weight slots (often bone index 0).
    # Expose only actual influences, then verify the native data contract.
    stored = [
        {"bone_index": int(item.bone_index), "weight": float(item.weight)} for item in weights if item.weight != 0
    ]
    _validate_weights(stored)
    return stored


def _validate_weights(bone_weights):
    if not isinstance(bone_weights, list) or not 1 <= len(bone_weights) <= 12:
        raise ValueError("bone_weights must contain 1 to 12 influences")
    seen = set()
    for item in bone_weights:
        if not isinstance(item, dict) or set(item) != {"bone_index", "weight"}:
            raise ValueError("Each influence must contain exactly bone_index and weight")
        index, weight = item["bone_index"], item["weight"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 65535:
            raise ValueError("bone_index must be an integer in [0, 65535]")
        if index in seen:
            raise ValueError("bone_index values must be unique")
        seen.add(index)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError("weight must be a finite number in [0, 1]")
        if not math.isfinite(weight) or not 0 <= weight <= 1:
            raise ValueError("weight must be a finite number in [0, 1]")
    if not math.isclose(math.fsum(item["weight"] for item in bone_weights), 1.0, abs_tol=1e-6):
        raise ValueError("bone_weights must sum to 1 within 1e-6")


def get_vertex_bone_weights(mesh_path: str = "", vertex_id: int = 0, profile_name=None, **kwargs) -> dict:
    """Read native skin weight attributes without changing the mesh."""
    try:
        _, api, mesh, profile = _resolve(mesh_path, vertex_id, profile_name)
        weights = _read(api, mesh, vertex_id, profile)
    except ValueError as exc:
        return skill_error("Cannot read DynamicMesh bone weights", str(exc))
    return skill_success(
        "Read DynamicMesh vertex bone weights",
        mesh_path=mesh.get_path_name(),
        vertex_id=vertex_id,
        profile_name=str(profile.profile_name),
        bone_weights=weights,
    )


def set_vertex_bone_weights(
    mesh_path: str = "", vertex_id: int = 0, bone_weights=None, profile_name=None, **kwargs
) -> dict:
    """Validate before mutation, create a missing profile, then return SDK readback."""
    try:
        _validate_weights(bone_weights)
        unreal, api, mesh, profile = _resolve(mesh_path, vertex_id, profile_name)
        native_weights = [
            unreal.GeometryScriptBoneWeight(bone_index=item["bone_index"], weight=float(item["weight"]))
            for item in bone_weights
        ]
        api.mesh_create_bone_weights(mesh, replace_existing_profile=False, profile=profile)
        _, valid = api.set_vertex_bone_weights(mesh, vertex_id, native_weights, profile=profile)
        if not valid:
            raise ValueError("The SDK rejected the vertex ID; the profile may have been created")
        stored = _read(api, mesh, vertex_id, profile)
    except ValueError as exc:
        return skill_error("Cannot write DynamicMesh bone weights", str(exc))
    return skill_success(
        "Wrote and read back DynamicMesh vertex bone weights",
        mesh_path=mesh.get_path_name(),
        vertex_id=vertex_id,
        profile_name=str(profile.profile_name),
        bone_weights=stored,
    )
