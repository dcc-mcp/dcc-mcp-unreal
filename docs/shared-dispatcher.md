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

An engine operation can pump Slate while an outer queue drain is active. Such
nested callbacks return before advancing work, publishing scene state, or
detaching the callback. The outer tick completes that work and any requested
cleanup. Direct recursive queue drains and calls from the wrong thread still
fail explicitly.

The any-affinity self-check dispatches its bounded engine identity reads to
this same main-thread queue. HTTP health/readiness waits stay on the caller's
worker so the host can continue pumping. A main-thread caller must select
`check_http=False`; requesting self-HTTP there returns an explicit error.

Default level loading saves the current level and stops if that save fails.
It keeps no old World reference across the map switch. New World inspection
starts only after the engine reports a successful load.

The declared Core floor, `0.20.13`, already exports the required dispatcher,
native HTTP queue attachment, bridge, and `ChunkedRunner` terminal callback
APIs. CI exercises that actual published dependency; no Core source overlay
or new minimum version is required for this adapter change.

## Candidate installation and host acceptance

Build the complete native adapter wheel through the
[normal native packaging entry](native-wheel-packaging.md). Install the exact
generated wheel and selected Core wheel into a new isolated interpreter:

```text
<private-python> -m pip install <qualified-core-wheel> <native-adapter-wheel>
<private-python> -m dcc_mcp_unreal.install_cli install --project <project.uproject> --dcc-path <ue-root> --python <private-python>
```

The installer validates the wheel's distribution ownership and complete plugin
payload before its receipt transaction. The fresh Editor consumes that installed
plugin through its normal bootstrap. Record the wheel SHA256, source commit,
imported `server.__file__`, Core version, engine version, receipt and fresh
PID/project identity. Source-wheel CI and synthetic scheduling tests establish
separate evidence from native compilation, installation and live Editor load.

Before running a sampler, verify `issubclass(UnrealMainThreadDispatcher,
HostUiDispatcherBase)` and the public `submit_chunked_runner` entry, then
exercise the typed tool through the normal gateway. Check multiple advancing
Editor frames, unrelated main-thread work, cancellation, one terminal result,
artifact completeness and hashes, and clean shutdown. Mock Slate tests and
native queue tests do not establish real Editor sampling, collision results,
video capture, or route acceptance.
