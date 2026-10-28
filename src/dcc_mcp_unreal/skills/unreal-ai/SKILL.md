---
name: unreal-ai
description: >-
  Domain skill - author and inspect Unreal Engine AI Blackboard data through
  runtime-gated Python editor APIs. Provides a typed capability preflight,
  bounded readback, and one minimal, transaction-backed key-authoring action.
  Behavior-tree graph, StateTree and EQS node editing are documented gaps and
  are not implemented here.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.7 syntax; runtime-gated, not native-qualified
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: authoring
    search-hint: "unreal ai blackboard behavior tree key author inspect preflight state tree eqs"
    tags: "unreal, ai, blackboard, behavior-tree, key, authoring, preflight"
    tools: tools.yaml
---

# Unreal AI (Blackboard authoring)

An independently usable, runtime-gated Python route to the smallest high-value
AI authoring primitive: **AI Blackboard data**. It gates the exact engine
version, Python-exposed API symbols and adapter native bridge it needs before
touching the editor, then performs one minimal, undoable action with a real
reflected readback. It reuses the existing plugin discovery, main-thread
dispatcher and `DccMcpAutomationLibrary.get_enabled_plugin_names` native bridge;
it does not add a discovery, threading or service architecture.

## Capability matrix (evidence-based)

A missing same-named directory is not proof of missing support. The matrix
below distinguishes what this adapter already covers, what is partial, and the
real gaps, based on the current tool inventory and code evidence. See
[the full matrix](../../../../docs/unreal-ai-capability-matrix.md) for file and
version evidence.

| Capability | Status | Evidence / route |
| --- | --- | --- |
| AI Blackboard data | **supported (this slice)** | `unreal-ai`: preflight, inspect, author one typed key, transaction + readback |
| Behavior-tree graph nodes | **gap** | no Python-exposed graph node authoring; needs the plugin's C++ `DccMcpAutomationLibrary` typed bridge |
| StateTree | **gap** | no tool; needs the StateTree plugin and a C++ typed bridge, version-gated |
| EQS queries | **gap** | no tool; needs a C++ typed bridge; unqualified across engine versions |
| AI Perception config | **partial** | actor/component tools exist (`unreal-actors`) but there is no AI editor facade |
| Gameplay Tags registry | **partial** | config editing only, no typed tag-registry tool |
| Blueprint / Niagara / MetaSound / UMG / PCG | **supported** | existing domain skills; not re-created here |

The reference design's own evidence note concedes that many version/native AI
operations are untested. This skill does not treat that list as maturity: every
operation is gated at call time and fails closed with a typed reason and one
`next_action` when a host does not expose the required surface. Graph-level AI
authoring is intentionally left as a documented C++-bridge gap rather than a
shallow one-to-one C++-module-to-skill mapping.

## Workflow

1. Call `ai_capability_preflight` first. It is read-only and returns `ready`,
   the engine version, available/missing API symbols, enabled plugins, and one
   deterministic `next_action` (`proceed`, `update_adapter_plugin`, or
   `unsupported_engine_version`). Proceed only when `ready` is true.
2. Call `inspect_ai_blackboard` to read the asset's typed keys. A missing asset
   returns `exists=false` with `readback_verified=true`; an existing wrong-class asset is
   rejected, never overwritten.
3. Call `author_ai_blackboard_key` with `asset_path`, `key_name` and a `key_type`
   from the schema enum. It creates an empty Blackboard only when the path is
   free and `create_if_missing` is true, then adds one key inside a scoped editor
   transaction. It verifies the new key through a reflected readback **before**
   saving, and returns a receipt with `key_count_before`, `key_count_after`,
   `mutation_state` and `recovery_errors`.
4. Re-run `inspect_ai_blackboard` to confirm the key in a fresh readback.

## Preflight, errors, and undo/cancel

- Preflight gates: Unreal Engine `>= 5.0`, the seven required Python-exposed
  symbols, and the adapter's native plugin-enumeration bridge. A failed gate
  yields `ready=false` and one machine-readable `next_action`.
- Typed errors carry a `reason` such as `preflight_not_ready`,
  `unsupported_api`, `invalid_asset_path`, `invalid_key_name`,
  `unsupported_key_type`, `duplicate_key`, `wrong_asset_class`,
  `readback_mismatch`, `save_failed` and `limit_exceeded`.
- Undo/cancel: the mutation is wrapped in `ScopedEditorTransaction`. On an
  in-transaction failure (readback mismatch, save failure, construction error)
  the transaction is cancelled and the previously observed key array is
  restored; the result reports `mutation_state=rolled_back` and any
  `recovery_errors`. Pre-condition rejections (preflight not ready, invalid
  input, duplicate key, wrong class, limit) fail before any mutation.
  Cancellation is advisory for an operation already running in the editor - it
  does not interrupt the editor process.

## Limits and honest boundaries

- At most 128 keys, 96-character key names, and a 240-character `/Game` package
  path; exceeding a limit rejects the operation rather than truncating.
- Real result readback is reflected editor state in the current session. A
  successful `save` is **not** proof of disk persistence or editor-restart
  survival. `generation_verified` and `reopen_verified` stay false.
- Real Unreal Editor / commandlet and GUI/PIE acceptance are separate gates and
  are not claimed here. The bounded unit contracts live in
  `tests/test_ai_blackboard_authoring.py`; a host commandlet probe is sketched
  in `tests/ue_ai_blackboard_commandlet.py`.
