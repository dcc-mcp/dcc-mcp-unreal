---
name: unreal-geometry-script
description: >-
  Domain skill - read and write per-vertex skin weights on existing Unreal
  DynamicMesh objects through the native Geometry Script API.
license: MIT
compatibility: Unreal Engine with Geometry Scripting and Python enabled; Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: runtime
    search-hint: "unreal dynamic mesh geometry script bone skin vertex weights"
    tags: "unreal, geometry-script, dynamic-mesh, skin-weights"
    tools: tools.yaml
---

# Dynamic Mesh Skin Weights

Use `get_vertex_bone_weights` and `set_vertex_bone_weights` with the exact
`get_path_name()` of an existing `unreal.DynamicMesh`. The mesh must already
exist in this editor session. Both tools run on the editor thread.

The default profile is the native SDK default. A named profile must be a
nonempty name with no whitespace and must not be the reserved name `None`.
Reads fail if the vertex or profile is missing. Writes create a missing
profile without resetting other profiles. Input weights must be finite,
nonnegative, normalized, use unique bone indices in the native uint16 range,
and contain at most 12 influences.

Results report the host readback instead of validating it: `bone_weights`
holds the host values with zero-weight native padding slots omitted, plus
`influence_count`, `weight_sum`, `normalized`, and `sum_abs_tol` diagnostics.
Native 16 bit quantization can leave a valid readback slightly off 1, so
`normalized` uses `1e-4` while input weights are still held to `1e-6`.

A write reports `success` once the SDK accepted the vertex. Its `verified`
flag and `readback_error` describe the readback only: a write that landed is
never reported as a write failure because the host stored something
unexpected. Only host values with no JSON-safe form (non-finite weights, or
bone indices outside uint16) reach `readback_error`.

These tools edit DynamicMesh attributes. They do not create skeletons,
bind a SkeletalMesh, deform geometry, save assets, or write animation.
