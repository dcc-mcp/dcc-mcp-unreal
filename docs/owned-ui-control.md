# Unreal owned UI Control composition

The normal shipped `Content/Python/init_unreal.py` can opt in to Core's public
owned pixels UI Control route. Default startup passes the historical Core
arguments, requires no new type or native getter, and remains compatible with
Core versions that predate typed UI Control. This integration does not start a
Native runtime, activate a window, observe pixels, provide input or record video
on startup.

Before launching the Editor, the operator sets both process environment values:

- `DCC_MCP_UNREAL_UI_CONTROL_PROFILE`: an absolute local owner JSON file.
- `DCC_MCP_UNREAL_UI_CONTROL_PROFILE_SHA256`: its exact lowercase SHA-256.

The trusted launcher must set these values before starting the Editor.
The shipped bootstrap freezes the pair for the
current module instance, including the disabled state. Within that instance,
later environment changes do not enable UI Control or replace its pin; every
start checks the file against the same digest. Trusted reload or re-execution
of the bootstrap reads the environment again and is outside this guarantee.
As an operator requirement, a different profile must use a new controlled
Editor launch rather than reload or re-execution. Sidecar mode rejects any
profile opt-in.

The closed JSON schema is `dcc-unreal-ui-control-owner/v1`. Required keys are
`schema`, `project_file`, `binary`, `sha256`, `runtime_version`, and
`allowed_actions`. Only `window_operations` and `recording_output_root` are
optional. For example, this is a template, not a selected runtime or grant:

```json
{
  "schema": "dcc-unreal-ui-control-owner/v1",
  "project_file": "F:/operator/Project/Project.uproject",
  "binary": "F:/operator/runtime/dcc-cua.exe",
  "sha256": "<exact lowercase binary SHA-256>",
  "runtime_version": "<exact qualified runtime version>",
  "allowed_actions": [],
  "window_operations": []
}
```

The profile must be one nonempty ordinary file, at most 16 KiB, with no hardlink,
symlink or reparse path. Its digest is checked before parsing. Duplicate keys,
unknown keys, ambiguous/nonlocal paths and incomplete pins fail closed. The
actual Editor `.uproject`, obtained from Unreal's `Paths` API, must match the
profile's canonical project path. The binary must already exist; Core checks
its exact hash, MCP identity/version and supported contract before opening a
task. A profile ceiling does not grant desktop authorization by itself.

The optional window operations are limited to distinct `activate` and
`restore_activate` values. They default to an empty ceiling. Only a later
explicit public ui-control request may consume these permissions; the adapter
never calls Win32 activation or automatically restores a window. The Core
public operations are `activate_window` and `restore_window`, respectively.
Minimize, frame changes and passive capture preparation are outside this
profile's scope.

When present, `recording_output_root` constructs public
`UiControlRecordingOptions(output_root=..., require_progress=True)`. Core must
validate the precreated ordinary output directory and support that progress
contract. An older Core that lacks `require_progress` fails explicitly. Omitting
the key grants no recording ceiling. Tests against Core versions without the
optional recording API skip the positive capability check and retain default
startup and explicit rejection coverage. Core artifact qualification is a
separate gate from this adapter integration.

With opt-in, the bootstrap requires the shipped native
`DccMcpEditorWindowLibrary.get_main_frame_identity_json()` getter. It validates
the closed `dcc-unreal-editor-main-frame/v1` success response, exact current
host/window PIDs and positive canonical decimal HWND. It never accepts a tool,
title, foreground-window guess or environment HWND. The server validates the
HWND's actual Win32 owner PID again before constructing and starting Core.
Missing getter, invalid identity, wrong Core type, missing HWND or a changed
configuration on an already running server is an error, with no fallback route.
The getter is point-in-time metadata; later lifetime/input fences remain Core
and Native responsibilities.

`UnrealMcpServer` and public `start_server` accept keyword-only `ui_control` and
`dcc_window_handle`. Only opt-in forwards these plus actual `os.getpid()` to
`DccServerOptions.from_env`. Options use the public `dcc_mcp_core.server` types.
Core's normal execution bridge supplies trusted metadata to its shipped
ui-control tools and strips tool-supplied runtime/scope overrides. The manual
`dcc_mcp_unreal_startup.py` helper remains the historical default startup; this
profile is consumed by the automatic shipped `init_unreal.py` entry point.
Reusing an active owned server requires the same option and exact HWND again;
omitting or changing either is refused. Stop the server before rebinding.
Calls without an owner configuration retain the default startup behavior.

Offline tests load the source files explicitly against normally installed
Core packages. They mock host and OS boundaries. One public
bridge test runs the installed Core `snapshot.py` through its real binder,
entrypoint and owned factory, then aborts at a mocked client constructor before
any session/process/observation. This verifies composition and strips forged
tool parameters; it does not qualify HTTP discovery, gateway, CLI/SDK, Native
protocol, hardware, foreground recovery, occlusion or recording. Those remain
separate actual acceptance gates after matching formal artifacts are frozen.
