---
name: unreal-pcg-pathfinding
description: Preflight bounded point-cloud Pathfinding inputs against actual native PCG settings and pins without running or saving a graph.
license: MIT
compatibility: Unreal Python host, Python 3.9+; runtime-gated PCG APIs documented in UE 5.5 and 5.7
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: scene
    search-hint: "unreal PCG pathfinding point cloud cost fitness multiplier preflight native pins"
    tags: "unreal, pcg, pathfinding, validation, procedural"
    tools: tools.yaml
---

# Native PCG Pathfinding preflight

## Scripts

`scripts/preflight_pcg_pathfinding.py` provides the typed preflight entry point.

Use `preflight_pcg_pathfinding` before wiring a PCG point-cloud Pathfinding
node. This is not AI NavMesh navigation and does not compute a path.

Supply point descriptors in one common Unreal coordinate frame, in centimeters.
A literal endpoint has `location: [x, y, z]`. An attribute-driven endpoint has
a plain named `attribute` and a bounded `values` array of vectors representing
the intended endpoint input. These JSON descriptors are validated, not converted
to PCGData or attached to the transient node.

The adapter rejects unknown fields, non-finite coordinates, missing numeric
cost attributes and unsupported selectors. It constructs new settings and a
scratch graph in `/Engine/Transient`, probes each requested property, reads the
values back, and reports the copied node's actual input/output pins. No existing
graph, level, asset, default object, plugin settings or service is modified.

`configuration_verified` covers transient property/pin readback only.
`execution_verified` is always false, and path status is `not_executed`, including
for empty clouds. Preflight success does not prove connectivity, generation,
attribute copying, complete/partial output, saving, or reproducibility.

The `goal_mapping_mode` field accepts an exact host enum member only when both
endpoints are attribute-driven; it is gated by real property and enum exposure,
not an engine version number. Collision/trace configuration, general property
selectors, graph persistence and generation are deliberately unsupported here.
The response's `optional_goal_mapping` reports property readability and observed
enum spellings; it does not claim that multiple-endpoint execution was tested.
See [scope and native acceptance](../../../../docs/pcg-pathfinding-workflow.md).
