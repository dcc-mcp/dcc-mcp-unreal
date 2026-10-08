---
name: unreal-level
description: >-
  Domain skill - Unreal Engine level and world management: inspect level state,
  load and save maps, read or edit world settings, and measure native collision
  distances in Editor or PIE worlds. Not for individual actor transform edits - use
  unreal-actors for that.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: scene
    search-hint: "unreal level world settings gravity time dilation save load map streaming line trace raycast collision distance ground floor doorway clearance centimeters"
    tags: "unreal, level, world, streaming, scene"
    tools: tools.yaml
---

# Unreal Level

Tools for active level inspection, map loading/saving, and world settings.

`focus_level_editor_viewport` is the structured editor-presentation action. It
closes existing Output Log and Message Log tabs or standalone tab windows,
activates the Level Editor, and focuses its active viewport through the native
Slate/LevelEditor bridge. It never sends keyboard or pointer input and fails
closed unless the native focus and tab-close postconditions are verified.

When an editor world is unavailable, tools report either
`reason=editor_not_loaded` or `reason=pie_or_mrq_active`. Active PIE/MRQ
responses include a typed status-poll action and the exact level-tool retry;
they do not create another poller or background job.

## Scripts

- `create_level`
- `focus_level_editor_viewport`
- `get_level_info`
- `line_trace` — Read native collision distance, hit point/normal and identities.
- `load_level`
- `save_level`
- `get_world_settings`
- `set_world_settings`

## Read-only spatial measurements

`unreal_level__line_trace` consumes the existing native
`SystemLibrary.line_trace_single` and `HitResult.to_tuple()` bindings. The tuple
method invokes native `BreakHitResult`; that function is intentionally not
exported separately as `GameplayStatics.break_hit_result` in Python. No new C++
bridge or engine rebuild is required. See
[spatial measurement validation](../../../../docs/spatial-measurements.md).

Pass explicit `world: editor` or `world: pie`. PIE never falls back to the editor
world and does not require a player pawn. Results include the actual world object
path; use `expected_world_path` on subsequent calls to reject a changed world.
All endpoints, positions and distances use Unreal world coordinates in **cm**:
left-handed, X forward, Y right, Z up. Normals are dimensionless world vectors;
`time` is the fraction along the segment. The host dispatches the tool to the
game thread through the existing Core host dispatcher. Direct Python callers
must also run both the trace and decoder on the game thread.
Returned endpoints reflect the actual native vector precision; a segment that
rounds to zero length on a legacy float32 host is rejected before tracing.

Choose `visibility` (default) or `camera`, the built-in native trace channels.
Object channels such as `pawn` are not trace-query indices. Simple collision is
requested with `trace_complex: false`; the query still follows the selected
trace-channel responses and does not perform a pawn capsule sweep. Ignored actors must use
exact object paths from the same world (for example the possessed pawn path),
not labels or bounds. Unknown paths fail. Endpoints must be finite, within
±10000000 cm, and define a positive segment at most 10000000 cm long.

A successful query has `context.status: hit` or `no_hit`. A hit reports
`blocking_hit`, `start_penetrating`, `distance_cm`, `location`, `impact_point`,
`normal`, `impact_normal` and actor/component `{name,path,class}` identities.
`distance_cm` comes from native FHitResult.Distance. A miss has false hit flags
and **null** hit fields, including distance and identities; `trace_length_cm`
still reports the sampled segment. Missing APIs, unavailable worlds, malformed
results and native exceptions are failures, never empty measurements.

For a floor sample, trace downward from above the candidate surface and retain
the hit point, upward impact normal, actor/component and query settings. For a
known opening, cast opposing collinear rays from one interior point toward its
two sides at the same recorded height. When both rays hit the intended opposite
surfaces without initial penetration, the sum of their distances measures the
collision gap along that line. Repeat at relevant heights and depths. A miss
does not establish a boundary or an unlimited free path. Initial penetration
is not a valid clearance measurement. A line measurement alone does not prove
that the player's capsule can traverse the opening; verify movement separately.

The independent Editor fixture covers known native floor/obstacle collisions in
an isolated editor world, including the actual Python native-break binding.
Running it proves only the engine version actually tested; it does not certify
imported-level collision, PIE player routes or FPP recordings. Unreal's Python
trace returns `None` for no blocking hit. During world transitions or without a
physics scene, that result cannot independently prove physics readiness; select
a stable active world and verify a known positive control before relying on misses.
