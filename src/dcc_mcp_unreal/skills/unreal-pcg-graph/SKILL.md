---
name: unreal-pcg-graph
description: Inspect bounded PCG topology or explicitly create, add nodes, edit scalar settings, connect pins and save a graph without implying execution or disk-reopen verification.
license: MIT
compatibility: Unreal Editor Python 3.9+ with detected PCG and editor scripting APIs; documented against UE 5.5, not native-qualified
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: scene
    search-hint: "unreal PCG graph create inspect nodes pins edges settings save"
    tags: "unreal, pcg, graph, authoring, structural"
    tools: tools.yaml
---

# Unreal PCG Graph

Prefer the optional official MCP PCGToolset on hosts where its actual registered
schemas are available. Discover with the existing official bridge; do not guess
operation names. This independently usable Python route gates the methods and
properties actually needed instead of assuming support from an engine version.

1. Inspect an existing `/Game/Folder/Asset` package path with `inspect_pcg_graph`,
   or explicitly `create` a new graph. Existing assets are never overwritten.
2. Use returned `node_id` object paths, not display titles or array indexes.
   `add_node` accepts an exposed PCGSettings subclass. `update_node` accepts
   int32 positions and exact-type scalar settings; enums, arrays, structs and
   object references are deliberately unsupported. Scalar writes require direct
   node-owned settings not shared by other nodes in the inspected graph; external
   settings/instances fail closed. Position-only edits remain available.
   Unknown fields fail closed.
3. `connect` / `disconnect` take `from_node`, `from_pin`, `to_node`, `to_pin`.
   Direction, graph ownership, data-type masks and connection cardinality are
   checked. Native compilation can still reject structurally compatible graphs.
4. Edits are transactions, never automatic saves or generation. On failure,
   inspect `mutation_state` and `recovery_errors`. Recovery compares observed
   topology and selected scalar settings; dirty flags/Undo history are not reset.
5. Explicit `save` checks the engine return and current-session readback. It does
   not unload packages or restart the editor and is not proof of disk persistence.

Limits: 256 nodes including input/output, 64 pins per direction per node, 4096
edges, 8192 edge references, 32 selected scalar setting names and a 1 MiB
serialized structural readback. Exceeding a limit rejects inspection
or mutation rather than validating a truncated graph. Nodes are not removed in
this slice because exact identity-preserving recovery is not established.

Generation remains `not_requested`, all execution/reopen verification flags are
false. Existing `refresh_pcg` is still trigger-only. Native generation completion,
freshness, output assertions and editor-restart acceptance remain tracked in
[#251](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/251).
See [workflow and evidence](../../../../docs/pcg-graph-workflow.md).
