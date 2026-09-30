"""Native Geometry Script skin weight access for existing DynamicMesh objects."""

from __future__ import annotations

import math

from dcc_mcp_core.skill import skill_error, skill_success

MAX_INFLUENCES = 12
# Callers own normalization, so inputs are held to the documented contract.
INPUT_SUM_ABS_TOL = 1e-6
# Native storage quantizes weights to 16 bits, so one influence can drift by
# ~1.5e-5. Readback is judged against a tolerance wide enough for MAX_INFLUENCES
# quantized influences instead of against the input tolerance, so native
# quantization is reported as a diagnostic and never as a failed read or write.
NATIVE_SUM_ABS_TOL = 1e-4


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


def _validate_input_weights(bone_weights):
    """Validate caller-supplied influences; runs before anything is mutated."""
    if not isinstance(bone_weights, list) or not 1 <= len(bone_weights) <= MAX_INFLUENCES:
        raise ValueError(f"bone_weights must contain 1 to {MAX_INFLUENCES} influences")
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
    if not math.isclose(math.fsum(item["weight"] for item in bone_weights), 1.0, abs_tol=INPUT_SUM_ABS_TOL):
        raise ValueError(f"bone_weights must sum to 1 within {INPUT_SUM_ABS_TOL}")


def _check_native_weights(bone_weights):
    """Reject only host values that have no JSON-safe form in a tool result."""
    for item in bone_weights:
        index, weight = item["bone_index"], item["weight"]
        if not 0 <= index <= 65535:
            raise ValueError(f"Native bone_index {index} is outside the uint16 range")
        if not math.isfinite(weight) or not 0 <= weight <= 1:
            raise ValueError(f"Native weight {weight!r} is not a finite value in [0, 1]")


def _diagnose(bone_weights):
    """Describe host weights; report them instead of judging native quantization."""
    total = math.fsum(item["weight"] for item in bone_weights)
    return {
        "bone_weights": bone_weights,
        "influence_count": len(bone_weights),
        "weight_sum": total,
        "normalized": bool(bone_weights) and math.isclose(total, 1.0, abs_tol=NATIVE_SUM_ABS_TOL),
        "sum_abs_tol": NATIVE_SUM_ABS_TOL,
    }


def _read(api, mesh, vertex_id, profile):
    """Read host weights and describe them without rejecting native quantization."""
    _, weights, valid = api.get_vertex_bone_weights(mesh, vertex_id, profile=profile)
    if not valid:
        raise ValueError("The vertex has no bone weights in the requested profile")
    # Unreal pads native storage with zero-weight slots (often bone index 0).
    # Expose only actual influences and report the host values unchanged.
    stored = [
        {"bone_index": int(item.bone_index), "weight": float(item.weight)} for item in weights if item.weight != 0
    ]
    _check_native_weights(stored)
    return _diagnose(stored)


def _read_back(api, mesh, vertex_id, profile):
    """Read back after a write; never let a readback problem fail the write."""
    try:
        return _read(api, mesh, vertex_id, profile), None
    except ValueError as exc:
        # Host values without a JSON-safe form are reported as a message rather
        # than dropped, so a write that already landed is still reported as one.
        return _diagnose([]), str(exc)


def get_vertex_bone_weights(mesh_path: str = "", vertex_id: int = 0, profile_name=None, **kwargs) -> dict:
    """Read native skin weight attributes without changing the mesh."""
    try:
        _, api, mesh, profile = _resolve(mesh_path, vertex_id, profile_name)
        stored = _read(api, mesh, vertex_id, profile)
    except ValueError as exc:
        return skill_error("Cannot read DynamicMesh bone weights", str(exc))
    return skill_success(
        "Read DynamicMesh vertex bone weights",
        mesh_path=mesh.get_path_name(),
        vertex_id=vertex_id,
        profile_name=str(profile.profile_name),
        **stored,
    )


def set_vertex_bone_weights(
    mesh_path: str = "", vertex_id: int = 0, bone_weights=None, profile_name=None, **kwargs
) -> dict:
    """Validate before mutation, create a missing profile, then report the write."""
    try:
        _validate_input_weights(bone_weights)
        unreal, api, mesh, profile = _resolve(mesh_path, vertex_id, profile_name)
        native_weights = [
            unreal.GeometryScriptBoneWeight(bone_index=item["bone_index"], weight=float(item["weight"]))
            for item in bone_weights
        ]
        api.mesh_create_bone_weights(mesh, replace_existing_profile=False, profile=profile)
        _, valid = api.set_vertex_bone_weights(mesh, vertex_id, native_weights, profile=profile)
        if not valid:
            raise ValueError("The SDK rejected the vertex ID; the profile may have been created")
        # The vertex is already written. Readback only describes host data, so it
        # must never turn this result into a write failure.
        stored, readback_error = _read_back(api, mesh, vertex_id, profile)
    except ValueError as exc:
        return skill_error("Cannot write DynamicMesh bone weights", str(exc))
    return skill_success(
        "Wrote DynamicMesh vertex bone weights",
        verified=readback_error is None and stored["normalized"],
        mesh_path=mesh.get_path_name(),
        vertex_id=vertex_id,
        profile_name=str(profile.profile_name),
        readback_error=readback_error,
        **stored,
    )
