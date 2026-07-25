---
name: unreal-cinematics
description: >-
  Domain skill — Sequencer shot and keyframe orchestration, camera cut tracks,
  and cinematic preview/render. Use when creating or editing Level Sequences,
  authoring camera animation, or rendering cinematics in Unreal Engine 5.
  Not for Blueprint scripting (unreal-blueprints) or runtime playback
  (unreal-runtime).
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+, UE 5.8+ for official MCP integration
allowed-tools: Read Bash Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: authoring
    search-hint: "sequencer cinematic camera cut track keyframe movie render level sequence shot"
    tags: [unreal, sequencer, cinematic, camera, keyframe, movie, render, sequence]
    tools: tools.yaml
---

# unreal-cinematics (Authoring stage)

Create and edit Level Sequences, add camera cuts and actor bindings,
author transform keyframes, control playback range, and render cinematic
output via the Movie Render Queue.

## Workflow

1. Call `create_level_sequence` to create a new sequence asset.
2. Use `add_actor_to_sequence` to bind actors as sequence tracks.
3. Author keyframes with `add_transform_keyframe`.
4. Add camera cuts via `add_camera_cut_track` for shot switching.
5. Set playback ranges with `set_playback_range`.
6. Inspect sequence state with `get_sequence_info`.
7. Render to video with `render_sequence_to_movie`.

When UE 5.8+ official MCP is available, the `unreal-official-mcp` skill
provides additional Sequencer tools through Epic's toolset registry.
Prefer the official path for complex shot workflows.

## Scripts

- `create_level_sequence` — Create a new Level Sequence asset in the Content Browser
- `open_level_sequence` — Open a Level Sequence in the Sequencer editor
- `add_actor_to_sequence` — Bind an actor as a track in a Level Sequence
- `add_transform_keyframe` — Add location/rotation/scale keyframes at a time
- `set_playback_range` — Set the sequence start and end frame
- `get_sequence_info` — Inspect tracks, bindings, and playback range
- `add_camera_cut_track` — Add a camera cut track for shot switching
- `render_sequence_to_movie` — Queue a cinematic render via Movie Render Queue
