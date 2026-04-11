---
name: unreal-actors
description: "Unreal Engine actor management — spawn, list, move, delete actors in the level"
dcc: unreal
version: "0.1.0"
tags: [unreal, actors, level, gameplay]
license: "MIT"
allowed-tools: ["Bash", "Read"]
depends: []
---

# unreal-actors

Unreal Engine actor management skill. Provides actions for working with actors in the level editor.

## Scripts

- `list_actors` — List all actors in the current level
- `spawn_actor` — Spawn an actor of a given class at a world position
- `delete_actor` — Delete an actor from the level by name
- `get_actor_transform` — Get the world transform of an actor
- `set_actor_transform` — Set the world transform of an actor
