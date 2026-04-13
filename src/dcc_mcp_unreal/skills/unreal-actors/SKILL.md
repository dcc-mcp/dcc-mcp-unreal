---
name: unreal-actors
description: "Unreal Engine actor management — spawn, list, move, delete actors in the level"
dcc: unreal
version: "0.1.0"
tags: [unreal, actors, level, gameplay]
license: "MIT"
allowed-tools: ["Bash", "Read"]
depends: []
tools:
  - name: list_actors
    description: "List all actors in the current level, optionally filtered by class"
    source_file: "scripts/list_actors.py"
  - name: spawn_actor
    description: "Spawn an actor of a given class at a world position"
    source_file: "scripts/spawn_actor.py"
  - name: delete_actor
    description: "Delete an actor from the level by name"
    source_file: "scripts/delete_actor.py"
  - name: get_actor_transform
    description: "Get the world-space location, rotation, and scale of an actor"
    source_file: "scripts/get_actor_transform.py"
  - name: set_actor_transform
    description: "Set the world-space location, rotation, and/or scale of an actor"
    source_file: "scripts/set_actor_transform.py"
---

# unreal-actors

Unreal Engine actor management skill. Provides actions for working with actors in the level editor.

## Scripts

- `list_actors` — List all actors in the current level
- `spawn_actor` — Spawn an actor of a given class at a world position
- `delete_actor` — Delete an actor from the level by name
- `get_actor_transform` — Get the world transform of an actor
- `set_actor_transform` — Set the world transform of an actor

## Usage Examples

### List all Static Mesh actors

```python
# MCP tool call: unreal_actors__list_actors
# params: {"actor_class_filter": "StaticMeshActor"}
```

### Spawn a cube at the origin

```python
# MCP tool call: unreal_actors__spawn_actor
# params: {
#   "actor_class": "/Script/Engine.StaticMeshActor",
#   "location_x": 0.0, "location_y": 0.0, "location_z": 0.0,
#   "label": "MyCube"
# }
```

### Delete an actor

```python
# MCP tool call: unreal_actors__delete_actor
# params: {"actor_name": "SM_Cube_1"}
```

### Get actor transform

```python
# MCP tool call: unreal_actors__get_actor_transform
# params: {"actor_name": "SM_Cube_1"}
```

### Move an actor to a new position

```python
# MCP tool call: unreal_actors__set_actor_transform
# params: {"actor_name": "SM_Cube_1", "location_x": 100.0, "location_y": 200.0}
```
