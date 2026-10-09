# Owner-selected UI Control runtime

The embedded Python bootstrap accepts an optional Core
`UiControlRuntimeOptions` through `UnrealMcpServer(ui_control=...)` or
`start_server(ui_control=...)`. This requires a Core build exposing that typed
API; older Core builds retain the default shared Host route and reject explicit
owned-runtime configuration. This option does not configure the native sidecar.

Construct the option in trusted host bootstrap code with an absolute executable
path, verified SHA-256, expected runtime version and explicit action/window
operation ceilings. Core owns executable verification, task authorization,
transport, native target validation and cleanup. Tool callers cannot select an
executable or enlarge these ceilings. The adapter continues to restrict the
target to its Unreal process; each UI task must bind the current exact PID/HWND.

Pass the same immutable option to `start_server` when reusing an active server,
or omit it to keep the existing configuration. A different option is rejected;
stop the server before configuring another runtime. No bootstrap call activates
a window, captures pixels, starts recording or retries an input operation.

With an owned pixels runtime, use the ordinary project `ui-control` route:
report `provider=dcc-cua`, runtime version and current PID/HWND, perform an
explicit owner-granted activate/restore operation, then request a fresh snapshot
in the same UI session. Keep the returned native identity, geometry and
observation provenance. Activation success does not certify valid capture
geometry or absence of occlusion. Pixels bypassing UIA do not bypass these
native checks. Verify the requested application effect independently and finish
with `ui_control__stop_computer_use`.

This bootstrap integration alone is not live Unreal acceptance. Validate
activation, capture, authorized input, application-state readback and cleanup
on the same current target before accepting a deployment.
