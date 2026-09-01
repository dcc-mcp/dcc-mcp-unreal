---
name: unreal-niagara
description: >-
  Domain skill — semantic Niagara VFX system authoring, component parameter
  configuration, and preview. Use when creating or editing
  Niagara particle effects, setting float/color/vector parameters,
  spawning Niagara actors in the level, or inspecting basic component state.
  Not for Chaos destruction (unreal-chaos) or material editing
  (unreal-materials).
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+; UE 5.8+ for semantic emitter/module/renderer authoring
allowed-tools: Read Bash Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: authoring
    search-hint: "niagara vfx particle effect emitter system float color vector parameter cascade"
    tags: [unreal, niagara, vfx, particle, emitter, effect, cascade]
    tools: tools.yaml
---

# unreal-niagara (Authoring stage)

Create and configure Niagara VFX systems, spawn them as actors in the
level, set float/color/vector parameters at runtime, inspect basic asset and
component state, and preview particle effects.

## Workflow

1. On UE 5.8+, call `author_niagara_system` to create and finalize emitters,
   module stacks, typed inputs, and renderers in one operation. This requires a
   fully loaded interactive Editor; commandlets fail closed before mutation.
2. Use `create_niagara_system` only when an intentionally empty system is enough.
3. Use `spawn_niagara_actor` to place the system in the current level.
4. Configure parameters via `set_niagara_float_parameter`,
   `set_niagara_color_parameter`, and `set_niagara_vector_parameter`.
5. Inspect the system with `get_niagara_system_info`.
6. Reset the system with `reset_niagara_system` during iteration.

When UE 5.8+ official MCP is available with `include_niagara_toolsets: true`,
the `unreal-official-mcp` skill provides additional Niagara authoring tools
through Epic's toolset registry. Prefer the official path for complex
emitter graph authoring.

## Scripts

- `author_niagara_system` — Author and finalize an emitter/module/renderer graph on UE 5.8+
- `create_niagara_system` — Create a new empty Niagara system
- `spawn_niagara_actor` — Spawn a Niagara system as an actor in the level
- `set_niagara_float_parameter` — Set a float parameter on a Niagara component
- `set_niagara_color_parameter` — Set a linear color parameter
- `set_niagara_vector_parameter` — Set a 3D vector parameter
- `get_niagara_system_info` — Resolve an asset or actor and inspect basic component state
- `reset_niagara_system` — Deactivate and reactivate a Niagara component
