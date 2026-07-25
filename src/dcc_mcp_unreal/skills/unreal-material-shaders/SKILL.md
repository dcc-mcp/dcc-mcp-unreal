---
name: unreal-material-shaders
description: >-
  Domain skill - Unreal Engine Material graph authoring and HLSL shader
  creation. Create Materials with blend modes and shading models, build
  expression node graphs, connect pins, compile shaders, create reusable
  Material Functions, author Custom HLSL nodes, and validate HLSL syntax.
  Complementary to unreal-materials (Material Instance + parameter assignment).
license: MIT
compatibility: Unreal Engine 5.4+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: authoring
    search-hint: "unreal material graph hlsl shader expression node compile function custom"
    tags: "unreal, material, hlsl, shader, graph, authoring"
    tools: tools.yaml
---

# Unreal Material Shaders

Material graph authoring and HLSL shader creation for Unreal Engine 5.4+.

- `create_material_graph` — Create a new Material asset with blend mode and shading model.
- `add_material_expression` — Add expression nodes (Constant, TextureSample, Multiply, Add, Lerp, Fresnel, etc.) to a Material graph.
- `connect_material_expressions` — Connect two expression pins in a Material graph.
- `compile_material` — Compile a Material and return shader compilation errors/warnings.
- `create_material_function` — Create a reusable Material Function.
- `create_hlsl_node` — Create a Custom HLSL expression node with source, inputs, and outputs.
- `validate_hlsl_syntax` — Pure syntax validation: parse HLSL source (no execution), return syntax errors. Read-only.
- `list_material_expressions` — List all expression nodes and their connections in a Material graph. Read-only.

## Scripts

All tools use `import unreal` as lazy import and `@skill_entry` decorator via `dcc_mcp_core.skill`.

## Usage Examples

### Create a material graph with simple color multiply

```python
# 1. Create the material
# MCP tool call: unreal_material_shaders__create_material_graph
# params: {"material_name": "M_ColorMultiply", "blend_mode": "Opaque", "shading_model": "DefaultLit"}

# 2. Add Constant3Vector for color
# MCP tool call: unreal_material_shaders__add_material_expression
# params: {"material_name": "M_ColorMultiply", "expression_type": "Constant3Vector", "params": {"R": 1.0, "G": 0.5, "B": 0.0}}

# 3. Add Multiply for combining
# MCP tool call: unreal_material_shaders__add_material_expression
# params: {"material_name": "M_ColorMultiply", "expression_type": "Multiply", "node_pos": [-400, 0]}

# 4. Connect Constant3Vector output → Multiply A pin
# MCP tool call: unreal_material_shaders__connect_material_expressions
# params: {"material_name": "M_ColorMultiply", "source_expression": "expr_0", "source_pin": "", "target_expression": "expr_1", "target_pin": "A"}

# 5. Compile
# MCP tool call: unreal_material_shaders__compile_material
# params: {"material_name": "M_ColorMultiply"}
```

### Create a custom HLSL node

```python
# MCP tool call: unreal_material_shaders__create_hlsl_node
# params: {
#   "material_name": "M_CustomHLSL",
#   "hlsl_code": "return sin(Parameters.TexCoords[0].x * 10.0);",
#   "inputs": [{"name": "UV", "type": "float2"}],
#   "output_type": "CMOT_Float1",
#   "description": "Sine wave pattern"
# }
```
