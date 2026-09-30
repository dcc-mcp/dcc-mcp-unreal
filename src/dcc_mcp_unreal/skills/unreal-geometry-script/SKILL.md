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
nonempty name with no whitespace. Reads fail if the vertex or profile is
missing. Writes create a missing profile without resetting other profiles.
Input weights must be finite, nonnegative, normalized, use unique bone
indices in the native uint16 range, and contain at most 12 influences.
Results contain the SDK readback, including native quantization/pruning.

These tools edit DynamicMesh attributes. They do not create skeletons,
bind a SkeletalMesh, deform geometry, save assets, or write animation.
