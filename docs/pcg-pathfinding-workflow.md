# Native PCG Pathfinding preflight

This is the first, deliberately narrow slice of [issue #253](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/253).
It does **not** close that issue or implement its end-to-end generation contract.
PCG point-cloud Pathfinding is separate from AI NavMesh navigation and PIE movement.

## Contract and side effects

`unreal-pcg-pathfinding` exposes `preflight_pcg_pathfinding` through the normal
typed skill catalog. It validates caller-provided JSON point and endpoint
descriptors, then constructs fresh native settings and a scratch graph node.
The adapter verifies `/Engine/Transient` ownership before property writes and
before graph edits. It never loads existing assets or writes a class default
object, never enables plugins, never calls generation and never saves.
The tool is marked non-read-only/non-idempotent because it allocates transient
Unreal objects. Those objects are left to normal engine garbage collection;
the adapter does not force global garbage collection or hold cached references.

No PCGData is materialized and no point-cloud input is connected. Therefore
configuration readback is useful for discovering the host's actual pins and
rejected properties, but cannot establish input compatibility at execution,
connectivity, path order, endpoints, metadata, collision behavior, completion
tags or deterministic results. `path_result.status` remains `not_executed`,
and complete/partial/reachable remain null. Empty clouds are valid descriptors
with a warning, not a successful empty native path.

## Bounded descriptor model

- `point_cloud`: 0–4096 point objects with three-component `position` values.
  Coordinates use centimeters in one already-aligned Unreal coordinate frame.
  Each coordinate is finite and within ±1e9 cm. There is no geospatial transform.
- Each point may have at most 16 plain named numeric `attributes`. Names must
  match `[A-Za-z_][A-Za-z0-9_]{0,127}`, excluding Unreal's `None` name. Names
  differing only by case on one point are rejected. General property selectors,
  expressions, vectors, strings and arbitrary metadata are not supported yet.
- Each endpoint is either `{location: [x, y, z]}` or
  `{attribute: "PositionName", values: [[x, y, z], ...]}` with 1–64 vectors.
  The second form describes a future separate endpoint input; it is not an
  attribute lookup into `point_cloud` and not native data creation.
- `search_distance` is greater than zero and at most 1e9 cm. `heuristic_weight`
  is 0–100, `maximum_fitness_penalty_factor` is 0–1e6, and `seed` is int32.
  These are adapter safety bounds, not claims about all engine limits.
- `DISTANCE` rejects an unused `cost_attribute`. `FITNESS_SCORE` requires a
  numeric cost on every point in [0, 1]. `COST_MULTIPLIER` requires costs in
  [0, 1e6] and warns about engine clamping of values below 1. A heuristic above
  1 warns that optimality is not guaranteed.
- Collision tracing is explicitly disabled. `use_path_traces`, trace structs,
  slope constraints and NavMesh settings are rejected as unknown caller fields.

## Host gate and readback

The runtime reads each requested settings property before any write, converts
named selectors using `PCGAttributePropertyInputSelector.set_attribute_name`,
and verifies scalar/vector/enum/selector readback. It then calls documented
`PCGGraph.add_node_copy` to create pins from the configured settings rather than
report stale pins from an unconfigured default node. The copied settings and
native pin properties must also be readable; unsupported return shapes fail
clearly. Diagnostics are bounded to 64 pins per direction and fixed property
names. No guessed pins, enum integers or hidden reflected methods are used.

`goal_mapping_mode` is optional and accepts only an exact member of the host's
`PCGPathfindingGoalMappingMode`. It requires attribute-driven endpoints and
actual `goal_mapping_mode` property exposure. A version string is reported as
identity only and never substitutes for these checks.
`optional_goal_mapping` reports readability and up to 64 enum member spellings
actually observed on the current host, so callers do not need to guess names.

## Verification status and remaining native acceptance

Cloud validation uses fake Python hosts and JSON Schema tests. **No engine or
plugin version is native-qualified by those tests.** Official API references
were checked for UE 5.5 and 5.7; this is documentation evidence, not execution.

On the real host, first call the typed preflight using both examples in
`tools.yaml`, record the engine version, actual returned pins, selector readback,
and failure for an absent optional property. Confirm project assets and level
remain unchanged. Repeating preflight should not retain references or alter
existing graphs.

The rest of #253 remains open: native input materialization/wiring, collision
configuration, executing and waiting for generation, bounded output inspection,
empty/disconnected/complete/partial fixtures, each cost mode, multiple endpoint
mapping, point order/tags/metadata assertions, deterministic reruns and graph
save/reopen. Integrate these with #251's graph workflow and #250's shared real
editor fixtures. Do not substitute a Python shortest-path implementation or
claim a settings preflight is native solver acceptance.

## Official references

- [UE 5.5 Pathfinding settings](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGPathfindingSettings?application_version=5.5)
- [UE 5.7 Pathfinding settings](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGPathfindingSettings?application_version=5.7)
- [UE 5.5 cost semantics](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGPathfindingCostFunctionMode?application_version=5.5)
- [UE 5.5 graph copy API](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGGraph?application_version=5.5)
- [UE 5.5 attribute selector](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGAttributePropertySelector?application_version=5.5)
- [UE 5.5 pin properties](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGPinProperties?application_version=5.5)
