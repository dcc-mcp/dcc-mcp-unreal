# Read-only collision measurements

The `unreal-level` skill's `line_trace` tool reads the first blocking collision
along an explicit world-space segment. Coordinates and distances use Unreal
centimeters. Select `world="editor"` or `world="pie"`; bind the selected world
with `expected_world_path` when making several related measurements. The tool
runs on Unreal's main thread and returns the selected world, requested query,
hit position and normals, native distance, and actor/component identities.
A miss is successful with `status="no_hit"`, false hit flags, and null hit data.
Unavailable APIs, invalid results, and unknown ignored actor paths are errors.

Unreal's Python `HitResult.to_tuple()` is the public native decoding entry
point, documented by Epic in
[`StructBase.to_tuple`](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/StructBase?application_version=5.7)
and the inherited
[`HitResult` API](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/HitResult?application_version=5.7).
`FHitResult` declares `HasNativeBreak` for
`GameplayStatics.BreakHitResult`; the Python struct wrapper invokes that native
function when producing the tuple. `BreakHitResult` is deliberately consumed
as a native struct break function rather than a separately exported Python
method. Its absence as `GameplayStatics.break_hit_result` does not mean native
hit decoding is unavailable. The adapter validates the tuple before returning
structured results.

This decoding repair needs no new DccMcp C++ method, UBT build, or Unreal restart
by itself. Delivering an updated bundled skill to an existing case is a separate
installation/loading step owned by that case. Read back the loaded product
version and source before attributing case measurements to the repair; replacing
a Python file alone does not establish that the running adapter loaded it.

## Independent UE 5.7/5.8 fixture

`scripts/run_spatial_query_smoke.ps1` creates a fresh Blueprint-only project
under this checkout's `dist/`. It enables the engine's `PythonScriptPlugin` and
`EditorScriptingUtilities`, disables default engine plugins, and explicitly
disables DccMcpUnreal and Fab. It starts `UnrealEditor-Cmd` with
`-ExecutePythonScript` and NullRHI. It does not build or install plugins, start
the gateway, or use an existing test project's files or running Editor instance.

Supply a Python payload containing a fixed compatible `dcc-mcp-core` wheel.
For example, prepare a dedicated payload with the engine's bundled Python:

```powershell
vx uv pip install --python F:\UE\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe `
  --target dist\smoke-python --no-deps dcc-mcp-core==0.20.41
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/run_spatial_query_smoke.ps1 `
  -UERoot F:\UE\UE_5.7 -PythonPayload dist\smoke-python -ExpectedCoreVersion 0.20.41
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/run_spatial_query_smoke.ps1 `
  -UERoot F:\UE\UE_5.8 -PythonPayload dist\smoke-python -ExpectedCoreVersion 0.20.41
```

Run the engines sequentially. Default outputs are `dist/spatial-smoke-ue57` and
`dist/spatial-smoke-ue58`. Existing output directories are preserved; supply a
fresh `-OutDir dist/spatial-smoke-ue57-retry1` for another attempt. The runner
accepts only output directories inside this checkout's `dist/`.

The script imports this checkout's product `src/` and the specified Core
payload. The fresh project loads the engine's Entry startup map. The fixture
checks that editor world's path and uses it without replacing the world from
a tick callback or saving level assets. It creates fixture-owned actors using
the engine's BasicShapes Cube with query collision enabled. The known geometry has
a floor top at Z=0 and wall inner faces at X=-125 and X=125 cm. It verifies:

- A downward ray returns the floor at 200 cm with upward normals and exact
  actor/component identities.
- Opposite rays from the same point return 125 cm each, yielding a measured
  250 cm clear gap from collision hits.
- A miss has null hit fields; ignoring a bound wall produces a miss.
- An unknown ignored actor path returns an explicit failure.
- The actual native floor `HitResult.to_tuple()` has the expected 18 values,
  distance, and actor/component bindings, without DccMcp's C++ library loaded.

`spatial-result.json` retains the typed results, native tuple fields, measured
values, engine/Core/product versions, imported source paths, Git HEAD, and
source SHA-256 digests. `runner.json` records the invocation and process exit;
`editor.log` retains engine output. Both a zero process exit and JSON
`success=true` are required. Failures retain their receipts and traceback.
Before and after each native setup call, the script atomically writes its
current phase to JSON and flushes a phase marker to stdout. A native crash can
therefore retain the last attempted setup call even when Python cannot catch it.

The fixture avoids viewport actor placement. It uses public `Object.call_method`
to invoke the known native `GameplayStatics.BeginDeferredActorSpawnFromClass`
and `FinishSpawningActor` UFUNCTIONs with explicit world, transform, collision,
and scale arguments. Their `BlueprintInternalUseOnly` metadata suppresses
generated Python method names, so the fixture does not assume those direct
Python methods exist. These actors do not request `RF_Transient`; they exist
only in this independent world's unsaved state and are destroyed during cleanup.
The receipt records this spawn route and actor lifetime explicitly.

Collision state creation and mesh compilation may be deferred. The fixture
uses the full Editor loop and public post-tick callbacks, keeping Python alive
until completion. It observes native hits for all three known obstacles over
actual Editor ticks before running the typed tool assertions. It records each
readiness probe and fails after bounded ticks/time if collision never becomes
ready. It does not sleep or assume that spawning an actor established queryable
collision. The Editor exits after cleanup and the final receipt.

This fixture proves the tested engine's collision and Python decoding path.
It does not certify an imported scene's collision setup, PIE character scale,
player routes, first-person visuals, screenshots, or video. Those remain real
case acceptance gates, and other engine versions require their own evidence.
