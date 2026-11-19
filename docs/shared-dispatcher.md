# Embedded Unreal scheduling

`UnrealMainThreadDispatcher` inherits the public Core `HostUiDispatcherBase`.
The existing single Slate post-tick callback drains Python and native HTTP
work together with a 4 ms cooperative budget and publishes scene context at
the existing cadence. Submissions do not create another timer, thread, or
job registry. `HostExecutionBridge.dispatcher` remains this same object.

Use a declared async, main-affinity tool returning the public `ChunkedRunner`
for operations that can be split into short host calls. Core advances at most
one chunk per pump and owns progress, cancellation, and terminal outcomes.
The budget controls when another step can start; it cannot pre-empt a running
Unreal API call. Each step must therefore be bounded. Native HTTP/Python work
and scene publication can proceed between chunks, provided each callback
returns promptly.

Closing first shuts down shared work and wakes waiting callers. Removal of
the Slate callback runs only on the host thread. A worker close waits for that
existing callback; if the Editor stops ticking, shutdown remains effective
and callback removal is reported as pending until the next tick. Repeated
close is idempotent. Queued Python work that times out is cancelled before a
later tick can execute it. A running call remains cooperative.

The declared Core floor, `0.20.13`, already exports the required dispatcher,
native HTTP queue attachment, bridge, and `ChunkedRunner` terminal callback
APIs. CI exercises that actual published dependency; no Core source overlay
or new minimum version is required for this adapter change.

## Candidate installation and host acceptance

Build a wheel with `python -m build --wheel`. Install the exact wheel into a
new, isolated Python payload directory with the host-compatible Python:

```text
python -m pip install --no-deps --target <candidate-python> <exact-adapter-wheel>
```

The fresh Editor must already have a supported, verified Core installation.
Use the existing project/plugin bootstrap in that fresh candidate only;
prepend `<candidate-python>` before importing `dcc_mcp_unreal`. Record the
wheel SHA256, source commit, imported `server.__file__`, Core version, engine
version, and fresh PID/project identity. Do not reload this module underneath
a running server or replace the active project's installed Python payload.
The wheel includes plugin source; this Python dispatcher change does not
claim a newly compiled native plugin.

Before running a sampler, verify `issubclass(UnrealMainThreadDispatcher,
HostUiDispatcherBase)` and the public `submit_chunked_runner` entry, then
exercise the typed tool through the normal gateway. Check multiple advancing
Editor frames, unrelated main-thread work, cancellation, one terminal result,
artifact completeness and hashes, and clean shutdown. Mock Slate tests and
native queue tests do not establish real Editor sampling, collision results,
video capture, or route acceptance.
