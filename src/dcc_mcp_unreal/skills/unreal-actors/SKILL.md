---
name: unreal-actors
description: >-
  Domain skill - Unreal Engine actor management: list, spawn, transform, and
  delete level actors. Use when inspecting or editing actors in the current
  Unreal Editor level. Not for Content Browser asset import/export - use
  unreal-assets for that.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Bash Read
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: authoring
    search-hint: "unreal actor list spawn delete transform level editor static mesh blueprint"
    tags: "unreal, actors, level, gameplay, transform"
    tools: tools.yaml
---

# Unreal Actors

Tools for actor-level operations in the active Unreal Editor level.

## Scripts

- `list_actors`
- `spawn_actor`
- `delete_actor`
- `get_actor_transform`
- `set_actor_transform`
