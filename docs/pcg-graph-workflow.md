# PCG graph structural authoring foundation

This is a bounded first slice of [#251](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/251),
not completion of its generation and persistence acceptance contract. It is
independent of the capability/setup changes in #261 and does not replace the
existing official MCP transport or change `refresh_pcg` behavior.

## Supported contract

The `unreal-pcg-graph` skill provides:

- `inspect_pcg_graph`: observed node object paths, native settings-class paths,
  positions, pins, data-type masks, connection cardinality, exact topology and
  optional scalar property readback.
- `edit_pcg_graph`: one explicit `create`, `add_node`, `update_node`, `connect`,
  `disconnect`, or `save` operation. Editing does not automatically save or
  request component generation.

Use package paths such as `/Game/PCG/MyGraph`, not filenames, object reference
strings or paths outside `/Game`. This conservative ASCII naming contract is
intentional. Existing assets are never overwritten. Redirected identities are
not edited. Native node object paths, not titles or array positions, identify
nodes within their owning graph. The identity must be re-observed after a rename.

`add_node` requires an actually exposed `PCGSettings` subclass. `update_node`
accepts an int32 position and at most 32 selected scalar properties whose Python
type exactly matches the current reflected value. Unknown properties,
nonfinite floats, type coercions, enums, structs, arrays and object references
are not silently accepted. Property-specific ranges remain engine-enforced,
with exact readback and attempted recovery on rejection or normalization.

Connections use the observed pin labels. Graph ownership, direction, overlapping
native type masks and both pins' connection cardinality are checked before the
transaction. These checks do not establish cycle validity, compilation or data
compatibility beyond the exposed masks. There is no invented `ValidateGraph` API.
Topology is reconstructed from the shared edge objects in `PCGPin.edges`; no
undocumented `PCGEdge` endpoint fields are assumed.

Limits are 256 nodes including graph input/output, 64 pins per direction per
node, 4096 edges, 8192 edge references, 32 selected scalar property names and a
1 MiB serialized structural readback. A limit failure is not partial validation:
inspection/edits stop rather than silently dropping topology from the result.

## Failure and save semantics

Edits require an available editor PIE-state query and are refused during PIE.
Mutation API methods and rollback requirements are checked before mutation.
Transactions record graph/node/settings/pin changes as relevant. A failed edit
attempts targeted inverse changes, then compares structural fingerprints and
selected setting values. `mutation_state=restored_readback` proves only that
those observations match; it does not restore dirty flags or Undo history.
`recovery_incomplete` includes bounded recovery errors and requires inspection
before retrying. Transaction cancellation is not treated as automatic rollback.

Creation failures report that the outcome requires inspection. Newly created
assets are never force-deleted automatically, because Unreal's delete APIs can
clear Undo history or affect references. Inspect the explicit target path before
retrying an uncertain creation. Node removal is not exposed until reliable
identity-preserving recovery has been established.

`save` is separate and checks `save_loaded_asset(..., only_if_is_dirty=False)`.
It can check out/save the target package, including other objects in that package,
per Unreal's documented behavior. A failed/uncertain save is not retried or
represented as success, and the asset is not deleted. A successful return plus
matching `load_asset` readback is explicitly described as **current editor object
cache readback**, not reopening from disk. `disk_reopen_verified` remains false.

`generation_status=not_requested`, `generation_verified=false` and
`execution_verified=false` never change in this slice. Compile success, fresh
execution, stale-data rejection, timeout/cancellation and valid empty output
remain unimplemented. `refresh_pcg` still acknowledges a trigger only.

## Official MCP and versioning

On a supported host with official PCGToolset schemas, prefer that route using
the existing official MCP bridge's list/describe/call workflow. Never derive
registered tool names from C++ method names. No official toolset is enabled,
service started, network call made, or version-based feature gate applied by
this skill. Engine identity is recorded from `SystemLibrary.get_engine_version`;
missing APIs fail closed independently of the version string.

These primary references informed the implementation. They are documentation
evidence for UE 5.5, not native qualification or a blanket minimum-version claim:

- [PCGGraph](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGGraph?application_version=5.5)
- [PCGNode](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGNode?application_version=5.5)
- [PCGPin](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGPin?application_version=5.5)
- [PCGPinProperties](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGPinProperties?application_version=5.5)
- [PCGDataType](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGDataType?application_version=5.5)
- [PCGGraphFactory](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGGraphFactory?application_version=5.5)
- [AssetTools](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/AssetTools?application_version=5.5)
- [EditorAssetLibrary](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/EditorAssetLibrary?application_version=5.5)
- [ScopedEditorTransaction](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/ScopedEditorTransaction?application_version=5.5)
- [Object mutation methods](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/_ObjectBase?application_version=5.5)
- [LevelEditorSubsystem](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/LevelEditorSubsystem?application_version=5.5)

## Verification status and native acceptance

Cloud tests use fakes and failure injection. They are not native Unreal evidence.
No editor build is qualified by this PR. No official sample assets are required
or acquired, and no plugin installation or settings changes are implicit.

The PC8 native coordinator should record engine build, loaded plugin versions,
OS, exact commit and fixture path before testing an independently authored graph:

1. Confirm all reflected methods/properties and `PCGDataType` integer conversion.
2. Create an unused graph path; capture its two graph endpoint node identities.
3. Add a supported settings node, change a scalar property/position, connect its
   observed compatible pins, inspect exact topology and disconnect/reconnect.
4. Attempt wrong-type properties, cross-graph identities, invalid pin labels and
   occupied single-connection pins; verify no unintended changes.
5. Save explicitly, record the structural fingerprint and selected scalar fields.
6. In a separate authorized editor reopen/restart, inspect again and compare the
   same nodes/settings/edges. Same-session `load_asset` does not satisfy this step.
7. Capture Undo/Redo and graph edits using existing scoped UI tools, plus semantic
   readback. Record failures/unsupported APIs without claiming successful execution.
8. Generation/completion/output acceptance must wait for the next #251 slice.

Keep #251 open until its remaining native graph-instance/generation lifecycle,
freshness, cancellation, persisted restart and output assertions are delivered.
