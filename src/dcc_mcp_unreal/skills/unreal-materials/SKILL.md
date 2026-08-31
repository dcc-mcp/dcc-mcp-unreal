---
name: unreal-materials
description: >-
  Domain skill - create reusable Material Instances, set typed material parameters,
  connect material-expression outputs to Customized UV inputs, and bind materials to
  Static Meshes, Geometry Caches, or live level actors in Unreal Engine.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: lookdev
    search-hint: "unreal material instance scalar vector texture parameter customized uv expression output assign mesh actor"
    tags: "unreal, material, material-instance, material-graph, customized-uv, shading, lookdev"
    tools: tools.yaml
---

# Unreal Materials

- `create_material_instance`
- `set_material_instance_parameters`
- `connect_material_expression_to_customized_uv`
- `assign_material`

`set_material_instance_parameters` routes scalar, vector, and texture overrides
through one native editor transaction. It rejects dirty packages, saves
synchronously, verifies the requested overrides and clean package state, and
restores the previous override arrays when mutation or persistence fails.

`connect_material_expression_to_customized_uv` is the typed material-root path for
Customized UV 0-7. Select exactly one source output by zero-based index or exact,
case-sensitive output name. The native editor bridge validates graph ownership,
records an undo transaction, saves synchronously, and verifies the saved connection.
It fails closed when the package already contains unsaved changes or a different
connection occupies the requested input unless `replace_existing=true` is explicit.
