# Typed spline grammar settings

This is a narrow, dependent authoring slice of
[#252](https://github.com/dcc-mcp/dcc-mcp-unreal/issues/252), building on the
[graph contract](pcg-graph-workflow.md). It adds no MCP tool and does not close
the spline creation, sampling, metadata, grammar execution or assembly workflow.

## Author through the existing graph tools

1. Inspect or explicitly create an owned graph using `unreal-pcg-graph`.
2. `add_node` with `settings_class: PCGSubdivideSplineSettings`. Use its returned
   `created_node_id`, not a fabricated node path or title.
3. `update_node` on that identity can now accept the following `settings`:

```json
{
  "grammar_selection": {
    "grammar_as_attribute": false,
    "grammar_string": "{[Fence,Post]:2,[Gap,Post]:1}*"
  },
  "module_info_as_input": false,
  "modules_info": [
    {"symbol": "Fence", "size": 200.0, "scalable": false},
    {"symbol": "Post", "size": 25.0, "scalable": false},
    {"symbol": "Gap", "size": 200.0, "scalable": true}
  ],
  "seed": 42,
  "use_seed_attribute": false,
  "accept_incomplete_subdivision": false
}
```

The scalar fields still require exact native reflected types/properties. The
module `size` contract is **Unreal centimeters**, positive and at most 1e9 cm.
There is no implicit unit conversion, mesh-bounds calculation or dimensional-fit
calculation. These are conservative adapter bounds, not Epic's maximum sizes.
Modules require `symbol`, `size`, `scalable`, and optionally `debug_color` as four
numbers in [0,1]. There must be 1–128 modules; symbols are unique ignoring ASCII
case, use 1–64 ASCII letters/digits/underscores, do not begin with a digit, and
cannot be `None`. Those restrictions are not a claim about Epic's full grammar
alphabet. Unknown keys, asset paths, nonfinite values and booleans as numbers
are rejected.

Fixed modules are ineffective when `module_info_as_input` is true. Such writes
are refused unless the same request explicitly sets it false. Switching that
mode on a connected node is refused: explicitly disconnect its edges first,
then reinspect actual pins and reconnect. No pin labels are guessed.

For attribute-driven grammar use exactly:

```json
{"grammar_selection": {"grammar_as_attribute": true, "grammar_attribute": "Grammar"}}
```

The name follows the same conservative naming rules. This configures a fresh
native input selector; it does not create, load or validate input spline data or
prove the attribute exists. Switching modes preserves the inactive native
literal/selector state. Property selections such as `$Position.X` and selector
suffix expressions are not authorable through this closed descriptor.

4. Inspect with `settings_names` including `grammar_selection`, `modules_info`
   and any changed scalar fields. Readback contains actual native values,
   including inactive grammar state, and a `native_state_fingerprint` covering
   each full bounded native struct export. It never includes raw export text.
5. Save only with the separate existing `save` operation. Save/readback in the
   current editor remains **not** a disk reopen. No generation is requested.

## Safety and evidence boundaries

Only the exact runtime `PCGSubdivideSplineSettings` class and its exact native
`PCGGrammarSelection`, `PCGSubdivisionSubmodule`, selector and Vector4 types are
accepted. Other nodes, subclasses, aggregates, object references and generic
struct descriptors are not opened up by this change. Ownership, PIE-state,
transaction and shared/external-settings guards remain in the graph layer.

All requested values and native properties are checked before modifying graph
objects. Recovery retains detached native struct copies and immutable canonical
JSON observations, not live property-array wrappers. Every apply and rollback
uses fresh `StructBase.copy()` values and checks their complete observations
against the immutable snapshots. Numeric display values preserve precision;
native export hashes also cover other/inactive reflected struct state. Export
text is never imported and cannot be supplied as an authoring input. Missing
copy APIs, same-wrapper copies and observably lossy copies are rejected. Correct
native value detachment is a required host contract and still needs native
qualification: distinct wrappers with incorrectly shared backing storage could
change the source during preparation before the final comparison detects it.
The adapter does not claim pre-transaction rollback for that broken host behavior.
Failed transactional recovery reports
`recovery_incomplete`, not an automatic Undo or restored dirty state.

The adapter validates descriptor shapes, names, duplicate module symbols and
numeric bounds. It **does not parse grammar** or identify referenced symbols.
Weighted/repeated alternatives and even malformed nonempty grammar strings are
preserved verbatim (maximum 4096 characters, no NUL). An unknown module reference
is therefore not discovered here. Native parsing, unfillable spans, module
placement, geometric fit, metadata preservation and deterministic output are
unverified. The result explicitly reports these unverified boundaries; setting
a seed is not proof of reproducible output. No custom string parser substitutes
for Epic's execution, and Epic warns that tight spline corners can produce
incorrect subdivision results.

`PCGSubdivisionSubmodule` has symbol, size, scalability and debug color, **no
mesh asset reference**. Asset mapping via an attribute set and a native mesh
selector is a separate contract and is not implemented. There are no downloads,
licensed sample assets, spawners or generated components in this slice.

## Native acceptance chain

Cloud tests use fakes. UE 5.5 Python API and UE 5.8 C++ documentation establish
the API design references, not a tested runtime. PC8's installed candidate
UE 5.8.1 CL56057345 must be verified as the **loaded** editor before testing;
there is no qualified native engine/plugin combination yet.

1. Record actual engine build, loaded adapter/PCG plugin identities, commit,
   session, owned fixture path and initial node/settings/pin observations.
2. Through the existing public graph tool, author literal and named-attribute
   grammar plus fixed modules. Check nested readback, inactive fields, colors,
   case handling, size in cm, seed/incomplete-fit properties and actual pins.
3. Confirm detached struct copies do not alias live settings. Test invalid
   descriptors, duplicates, unknown fields, unsupported class/property/type,
   external/shared settings and connected-node mode changes without asset edits.
4. Use scoped editor UI Undo/Redo, then semantic readback of all typed fields and
   fingerprints. Explicitly save, restart/reopen in the owned workflow, and
   compare persisted state. Do not call same-session load a reopen.
5. **Separately pending:** construct open/closed and transformed spline fixtures,
   connect actual compatible pins, execute native grammar, and observe completion
   plus output. Cover invalid/missing-symbol grammar, incomplete-fit policy,
   weighted alternatives, repeated-seed output, tight corners and module fit.
   Full generation/freshness and output acceptance depends on the next #251
   lifecycle slice; this codec never reports those steps as passed.

## Primary references

- [Subdivide Spline Python settings, UE 5.5](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGSubdivideSplineSettings?application_version=5.5)
- [Grammar selection Python struct, UE 5.5](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGGrammarSelection?application_version=5.5)
- [Module Python struct, UE 5.5](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGSubdivisionSubmodule?application_version=5.5)
- [Selector methods, UE 5.5](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGAttributePropertySelector?application_version=5.5)
- [Struct copy/export methods, UE 5.5](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/StructBase?application_version=5.5)
- [Subdivision base settings, UE 5.8](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/PCG/UPCGSubdivisionBaseSettings)
- [Grammar struct, UE 5.8](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/PCG/FPCGGrammarSelection)
- [Module struct, UE 5.8](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/PCG/FPCGSubdivisionSubmodule)
- [Units of measurement](https://dev.epicgames.com/documentation/unreal-engine/units-of-measurement-in-unreal-engine)
- [Shape Grammar workflow and limitations](https://dev.epicgames.com/documentation/en-us/unreal-engine/using-shape-grammar-with-pcg-in-unreal-engine)
- [Separate mesh selector contract](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PCGMeshSelectorByAttribute)
