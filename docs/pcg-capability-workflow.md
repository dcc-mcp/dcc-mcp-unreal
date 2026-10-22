# PCG capability discovery and official-tool workflow

## Evidence, not an implementation claim

Load `unreal-pcg` and call `inspect_pcg_capabilities` before choosing a route.
The read-only tool checks a fixed Python surface for graph, generation, grammar,
spline and PCG Pathfinding APIs. It reports the exact observed names and engine
version, current-process plugin registry evidence and descriptor-file existence.
It does not create UObject instances or inspect/load a graph asset.

- `available`: the listed Python member was observed, not executed.
- `unavailable`: that member was not observed on the inspected Python surface.
- `unknown`: metadata inspection could not establish a result.
- `partial`: a feature's individual checks have differing results. Inspect the
  checks rather than treating this as blanket feature support.
- `execution_verified=false` and `native_bridge_verified=false`: intentionally
  unchanged by observation. No compile, signature or runtime acceptance test ran.

Plugin `installed`, `enabled` and `discovered` are separate evidence. A registry
miss without a descriptor path does not prove a plugin is absent from every
directory; installation stays unknown. The tool never scans the entire engine,
enables a plugin, starts HTTP, generates data or saves a project. Static Python
inspection may not see dynamic-only wrappers; it must not rule out native APIs.

## Choose the route from the actual host

PCG is not uniformly a UE 5.8-only feature. Epic documents
[graph scripting in 5.2](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGGraph?application_version=5.2)
and [grammar subdivision](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGSubdivideSplineSettings?application_version=5.5)
and [PCG Pathfinding](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGPathfindingSettings?application_version=5.5)
in 5.5. These reference points are not supported-version promises. A customized
engine can expose a different surface; even a new version can lack a plugin.

The Pathfinding inspection concerns the PCG point-cloud node, not AI NavMesh.
The optional `goal_mapping_mode` property is checked independently instead of
assuming every version has the same settings schema. Spline components and PCG
spline data are also reported separately. None of these observations adds the
graph/grammar/spline/pathfinding authoring workflows tracked in later issues.

[PluginBlueprintLibrary](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PluginBlueprintLibrary?application_version=5.4)
supplies the read-only registry queries. Missing metadata functions on older
hosts yield unknown plugin state, not an exception or automatic setup attempt.

## Optional official MCP path (UE 5.8+)

1. Load `unreal-official-mcp`; call `official_mcp_bridge(operation="status")`.
   These HTTP calls must run with `affinity:any`, not on the editor game thread.
2. If setup is needed and a project change is explicitly intended, call
   `prepare_official_mcp(include_pcg_toolset=true)`. The default is false.
   Installed descriptors and configuration are checked before mutation.
   Respect any dependency/rollback failure and do not claim the plugin is live
   merely because configuration was written.
3. If a restart is required, restart through the normal authorized workflow,
   reconnect to the intended editor and check status again.
4. Call `list_toolsets`, then `describe_toolset` using the exact returned name.
   Do not guess an MCP tool name from a C++ `UPCGToolset` method.
5. Only then call a discovered tool with its actual schema. Mutating graph calls
   require the intended asset scope and should be incremental, not concurrent.
6. Validate structure, save/reopen, and check generation completion/output
   separately. A trigger response or a last-execution data view is not proof of
   a new successful run. Graph lifecycle acceptance is tracked separately.

Epic marks [PCGToolset](https://dev.epicgames.com/documentation/unreal-engine/API/PluginIndex/PCGToolset)
Experimental. Its installed descriptor lives at
`Engine/Plugins/Experimental/Toolsets/PCGToolset/PCGToolset.uplugin`.
See the [official PCG/MCP workflow](https://dev.epicgames.com/documentation/unreal-engine/working-with-pcg-and-llms-using-unreal-mcp-in-unreal-engine)
and [toolset API](https://dev.epicgames.com/documentation/unreal-engine/API/Plugins/PCGToolset/UPCGToolset)
for reference, while treating runtime discovery as authoritative for exposed
names and schemas.

## Verification boundary

Automated tests cover fake old/partial/new Python surfaces, unavailable metadata,
read-only behavior, opt-in setup, preservation, idempotence and write-failure
rollback. They do **not** prove native Unreal or CUA behavior.

On an actual supported editor, record the UE build/plugins, compare installed,
enabled and registered-tool states, run the bridge discovery workflow, and
verify explicit setup plus restart on a disposable project. Confirm inspection
leaves project/graph state unchanged. This native acceptance is still pending;
[issue #249](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/249) must not be closed
on mocked tests alone. No asset downloads or license acceptance are needed for
this discovery/setup change.
