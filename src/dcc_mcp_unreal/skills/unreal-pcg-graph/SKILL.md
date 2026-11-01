---
name: unreal-pcg-graph
description: Inspect bounded PCG topology or explicitly create, add nodes, edit scalar or typed spline grammar settings, connect pins and save a graph without implying execution or disk-reopen verification.
license: MIT
compatibility: Unreal Editor Python 3.9+ with detected PCG and editor scripting APIs; documented against UE 5.5, not native-qualified
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: scene
    search-hint: "unreal PCG graph create inspect nodes pins edges grammar spline modules settings save"
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
   int32 positions and exact-type scalar settings. The only aggregate exceptions
   are `grammar_selection` and `modules_info` on exact native
   `PCGSubdivideSplineSettings`; use their closed schemas, not arbitrary structs.
   Settings writes require direct
   node-owned settings not shared by other nodes in the inspected graph; external
   settings/instances fail closed. Position-only edits remain available.
   Unknown fields fail closed.
3. `connect` / `disconnect` take `from_node`, `from_pin`, `to_node`, `to_pin`.
   Direction, graph ownership, data-type masks and connection cardinality are
   checked. Native compilation can still reject structurally compatible graphs.
4. Edits are transactions, never automatic saves or generation. On failure,
   inspect `mutation_state` and `recovery_errors`. Recovery compares observed
   topology and selected settings, including full typed struct fingerprints; dirty flags/Undo history are not reset.
5. Explicit `save` checks the engine return and current-session readback. It does
   not unload packages or restart the editor and is not proof of disk persistence.

Limits: 256 nodes including input/output, 64 pins per direction per node, 4096
edges, 8192 edge references, 32 selected setting names and a 1 MiB
serialized structural readback. Exceeding a limit rejects inspection
or mutation rather than validating a truncated graph. Nodes are not removed in
this slice because exact identity-preserving recovery is not established.

Generation remains `not_requested`, all execution/reopen verification flags are
false. Existing `refresh_pcg` is still trigger-only. Native generation completion,
freshness, output assertions and editor-restart acceptance remain tracked in
[#251](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/251).
See [workflow and evidence](../../../../docs/pcg-graph-workflow.md).

## Spline grammar settings

Use the existing `add_node` operation with `PCGSubdivideSplineSettings`, then
`update_node` with its observed identity. A grammar descriptor selects either
`grammar_as_attribute: false` with `grammar_string`, or `grammar_as_attribute:
true` with a plain `grammar_attribute` name. Text is preserved, **not parsed**.
`modules_info` accepts 1–128 unique ASCII symbols with positive `size` in Unreal
centimeters (maximum 1e9), `scalable`, and optional four-component `debug_color`.
Fixed modules require effective `module_info_as_input: false`. Disconnect the
node explicitly before switching a connected node from module-input mode.

No mesh path belongs in a subdivision module. No input attributes, spline
components or assets are created by these descriptors. Inspector readback includes
inactive grammar fields and a bounded native-state fingerprint so recovery cannot
ignore hidden selector state. Syntax, referenced symbols, geometric fit, asset
mapping, generation and deterministic output remain unverified. See
[grammar workflow and limits](../../../../docs/pcg-grammar-workflow.md).
