# Unreal native engine capability matrix (AI vertical slice)

This document is the evidence companion to the `unreal-ai` domain skill. It
records, with real code and version evidence, which Unreal Engine AI
capabilities the `dcc-mcp-unreal` adapter already covers, which are partial,
which are real gaps, and which are not applicable. A missing same-named skill
directory is **not** treated as proof of missing support: coverage is judged by
registered tools and code paths, not directory names.

Scope: the design reference used for this comparison was a community Unreal MCP
plugin (dev branch, MIT licensed) whose standout domain is AI (BehaviorTree,
Blackboard, StateTree, EQS). Its own evidence note concedes that many
version/native operations are untested. Accordingly this adapter does **not**
treat that feature list as maturity, does not copy or embed that project, and
does not wrap the deliverable in its name. The work here is an independent,
small, verifiable vertical slice that reuses this adapter's existing
architecture.

## Matrix

| Unreal capability | Status | Real evidence in this adapter |
| --- | --- | --- |
| AI Blackboard data | **supported (this slice)** | `src/dcc_mcp_unreal/skills/unreal-ai/`: `ai_capability_preflight`, `inspect_ai_blackboard`, `author_ai_blackboard_key` + `scripts/_ai_blackboard.py`. Version/plugin/API preflight, bounded readback, one typed key authoring with `ScopedEditorTransaction` rollback. Verified by `tests/test_ai_blackboard_authoring.py`. |
| Behavior-tree graph nodes | **gap** | No tool registers BT graph node creation/editing anywhere in `skills/*/tools.yaml` (24 domains, ~140 tools). Unreal's Python API does not expose BT graph node authoring across supported versions. The correct route is a follow-up slice adding a version-gated UFUNCTION to `unreal/plugin/Source/DccMcpUnreal/Private/DccMcpAutomationLibrary.cpp`, following the existing `AuthorNiagaraSystemJson` typed-bridge pattern (preflight, `FScopedTransaction`, rollback, JSON receipt). Not faked here. |
| StateTree | **gap** | No StateTree references in `src/`, `unreal/` or `tests/`. StateTree is an optional plugin (UE 5.x) and its editor authoring surface is C++/plugin-gated, not Python-exposed. Needs plugin preflight plus a C++ typed bridge. |
| EQS (Environment Query) | **gap** | No EQS references. Query authoring is editor-only C++ in most versions; needs a C++ typed bridge and per-version qualification. |
| AI Perception config | **partial** | General component/actor tools exist under `unreal-actors` (spawn/attach/set transform), so an agent can manipulate a perception component indirectly, but there is no AI-specific perception editor facade. |
| Gameplay Tags registry | **partial** | Project config tooling exists (`unreal-project-config`) for descriptor editing, but there is no typed GameplayTags registry authoring tool. |
| Blueprint graph | **supported** | `unreal-blueprints`: create class, add nodes, connect, compile, add variables. Plus `DccMcpAutomationLibrary` C++ material/graph helpers. |
| Niagara | **supported** | `unreal-niagara` incl. `author_niagara_system` through the UE 5.8 `AuthorNiagaraSystemJson` C++ typed bridge (version-gated, with rollback). |
| MetaSound | **supported** | `unreal-metasound`: full graph authoring/validation tools. |
| UMG | **supported** | `unreal-umg`: widget blueprints, animations, bindings. |
| PCG | **supported** | `unreal-pcg-graph` (bounded topology inspection + explicit typed edits) and `unreal-pcg`. |
| Cinematics / Sequencer | **supported** | `unreal-cinematics`: sequences, tracks, keyframes, render queue. |
| Materials / Chaos / Level / Assets / PIE | **supported** | Dedicated domain skills with registered tools (see `skills/*/tools.yaml`). |
| Native plugin discovery | **supported / reused** | `DccMcpAutomationLibrary.get_enabled_plugin_names` (C++) and `plugin_preflight.py` are reused by the AI preflight for the plugin gate. |
| Cancel of an in-flight editor operation | **not applicable** | Cancellation is advisory (transaction rollback + restored state); the adapter never terminates a running editor operation, matching the reference design's advisory-cancel semantics. |

## Why one small slice

Rather than a mechanical one-to-one mapping of C++ modules to skills, this work
implements a single, high-value, independently verifiable primitive - authoring
one typed AI Blackboard key - with the full contract the design calls for:
version/plugin preflight, a minimal action, real result readback, typed errors,
and undo/cancel semantics. It reuses the adapter's thin server, main-thread
dispatcher, plugin preflight and C++ automation bridge rather than adding a new
discovery, threading or MCP service architecture.

The deeper AI authoring (BT graph nodes, StateTree states, EQS queries) is left
as a documented, coherent gap. Implementing it correctly requires Python-unexposed
APIs to be exposed through the existing `DccMcpAutomationLibrary` C++ typed
bridge with per-engine-version qualification and real Editor/commandlet
acceptance - a separate, larger slice. This PR does not claim that work.

## Verification boundaries

- **In this PR**: bounded, mock-based Python contract tests
  (`tests/test_ai_blackboard_authoring.py`) covering preflight gating,
  readback, typed errors, duplicate/limit rejection, rollback on readback
  mismatch and save failure, and the tools.yaml/SKILL.md contracts. All new
  Python files are checked for Python 3.7 syntax compatibility
  (`ast.parse(..., feature_version=(3, 7))`), respecting the project's host
  compatibility floor.
- **Separate gates (not claimed)**: a real Unreal Editor commandlet probe
  (`tests/ue_ai_blackboard_commandlet.py` sketch), GUI/PIE acceptance through
  the project's DCC-CUA binding, and any CI that compiles the C++ plugin. These
  require a live host and are explicitly out of scope for this headless,
  bounded-test PR.
