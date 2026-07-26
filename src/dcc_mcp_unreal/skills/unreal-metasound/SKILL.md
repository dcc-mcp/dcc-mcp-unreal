---
name: unreal-metasound
description: >-
  Unreal Engine MetaSound Source authoring through the reflected Builder API:
  create sources, add typed inputs and exact registered nodes, connect opaque
  vertex handles, set defaults, inspect nodes, build, save, and validate. Use
  for procedural audio graphs in Unreal Engine 5.4+. Not for arbitrary asset
  management or Blueprint gameplay logic.
license: MIT
compatibility: Unreal Engine 5.4+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "1.0.0"
    layer: domain
    stage: authoring
    search-hint: "metasound, audio graph, builder, oscillator, filter, sound design, procedural audio, MetaSound Source"
    tags: "unreal, metasound, audio, graph, authoring, domain"
    tools: tools.yaml
---

# Unreal MetaSound Tools

Author MetaSound Source assets through Unreal's public reflected APIs:
`MetaSoundBuilderSubsystem`, `MetaSoundEditorSubsystem`, and
`EditorValidatorSubsystem`.

## Workflow

1. Call `unreal_metasound__create_metasound_source`. Keep the returned initial
   output/input handle tokens.
2. Add graph inputs or nodes. Nodes require an exact registry identity
   (`namespace`, `class_name`, `variant`, `major_version`); this skill never
   maps a broad label such as "Filter" to an arbitrary class.
3. Use the exact vertex handles returned by create/add/inspect with
   `unreal_metasound__connect_metasound_nodes`.
4. Set supported graph-input defaults, then build and validate.

For example, Unreal 5.8 registers a sine oscillator as:

```json
{
  "namespace": "UE",
  "class_name": "Sine",
  "variant": "Audio",
  "major_version": 1
}
```

## Handle contract

Node and pin handles are opaque Unreal Builder tokens:

```text
(NodeID=0123456789ABCDEF0123456789ABCDEF)
(NodeID=0123456789ABCDEF0123456789ABCDEF,VertexID=FEDCBA9876543210FEDCBA9876543210)
```

Do not edit or synthesize them. A mutating call verifies that each handle
belongs to the target graph before changing it.

## Supported defaults

Graph inputs support `Bool`, `Float`, `Int32`, and `String` literals. Object,
WaveTable, and array literals need additional asset/type contracts and are
intentionally rejected instead of being guessed.

## Validation boundary

`validate_metasound_graph` runs Unreal Data Validation and reports graph input
and output names exposed by the Builder. It fails when validation is
inconclusive. It does not claim private graph traversal, exhaustive cycle
analysis, or compile diagnostics that Unreal's Python API did not return.

## Safety

- Asset paths must be package paths under `/Game` using letters, digits, and
  underscores.
- Mutations run on the Unreal main thread, check every Builder result enum,
  and require Unreal to confirm the asset save.
- Unknown engine versions, missing plugins, invalid handles, and unsupported
  literal types fail closed.
- No `exec`, `eval`, subprocess, or arbitrary Python execution is exposed.
