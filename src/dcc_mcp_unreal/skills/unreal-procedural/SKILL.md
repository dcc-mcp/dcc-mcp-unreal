---
name: unreal-procedural
description: Capability-gated Unreal procedural workflows for PCG manual overrides, Procedural Vegetation, Nanite Foliage, Mesh Terrain, MegaLights, and Substrate.
license: MIT
compatibility: Unreal Python host, Python 3.9+; feature APIs are detected at runtime
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "1.0.0"
    layer: domain
    stage: authoring
    search-hint: "unreal PCG manual override procedural vegetation Nanite Foliage Mesh Terrain MegaLights Substrate"
    tags: "unreal, procedural, pcg, vegetation, nanite, terrain, rendering, substrate"
    tools: tools.yaml
---

# Unreal procedural workflows

Start with `inspect_procedural_capabilities`. It performs read-only host
reflection and reports enabled plugins, observed classes, engine version and a
feature-specific status. Engine version alone is never treated as proof of
support.

Use `validate_procedural_workflow` to create a bounded request plan before a
feature-specific native mutation. The plan records version boundaries,
explicit intent, target RHI or renderer requirements, ownership evidence and
the required post-state readback.

PCG manual overrides require an owned `dcc-cua` window record containing the
runtime version, target PID and HWND before selection or input. The semantic
contract does not provide a fallback to a generic browser or desktop driver.

The newer Unreal features remain experimental or platform-dependent. A
validated plan is not execution evidence. Native skills must probe the host
again immediately before mutation, save/reopen where applicable, and return
the actual readback or an explicit unsupported result.

## Scripts

- `inspect_procedural_capabilities`
- `validate_procedural_workflow`

