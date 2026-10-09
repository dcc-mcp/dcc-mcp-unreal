---
name: unreal-lifecycle
description: >-
  Inspect and request normal Editor close for an explicitly owned test launch.
  Uses native main-thread dirty/busy checks and MainFrame close; never kills a process.
license: MIT
compatibility: Unreal Engine 5.0+ embedded Python, Windows native plugin, Python 3.9+
allowed-tools: Bash Read
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: validation
    search-hint: "unreal editor lifecycle safe close stop owned test launch dirty busy"
    tags: "unreal, lifecycle, close, stop, ownership"
    tools: tools.yaml
---

# Owned Editor close

Ordinary artist hosts have no close capability. A trusted launcher opts in before
plugin startup with `DCC_MCP_UNREAL_CLOSE_OWNER`, `DCC_MCP_UNREAL_CLOSE_SESSION`
(ASCII letters, digits, `.`, `_`, `-`, 1–128 characters) and a random 32-byte nonce
encoded as 64 lowercase hex characters in `DCC_MCP_UNREAL_CLOSE_NONCE`. The plugin
captures these once, binds the actual Windows PID, 64-bit creation FILETIME and
absolute normalized project filename, and removes the nonce from its environment.
Keep the launcher secret in memory; never put it in tool arguments or receipts.
This capability is for isolated test launches, not a generic artist-host quit.

`inspect_editor_close` reports actual binding, dirty/busy refusal and the current
MCP instance UUID. `request_editor_close` requires that UUID and the exact native
binding, a unique UUID request ID and a 13-digit Unix millisecond expiry at most
two seconds ahead. The launcher computes the `proof` using Python standard library:

```python
fields = [instance_id, owner, session, str(host_pid), creation_filetime, project_file, request_id, expires_unix_ms]
message = "dcc-unreal-editor-close/v1\n" + "\n".join(fields)
proof = hmac.new(nonce.encode("ascii"), message.encode("utf-8"), hashlib.sha1).hexdigest()
```

This uses HMAC-SHA1 (160-bit authentication), not an unkeyed SHA1 digest. The nonce
and expected proof are never returned or logged by this adapter. Request proofs
expire quickly; they are still credentials and should not be published.

Native admission and the single deferred execution both reject changed host
binding, unattended/commandlet mode, dirty world/content, saving/loading/GC/slow
tasks, missing/debugging Slate, modal windows, lighting builds, and active **or
queued** PIE/SIE. End owned PIE separately and save explicitly before requesting
close. A refusal does not save, discard or queue a MainFrame close.

An admitted request is consumed once. Duplicate authenticated requests do not
extend its deadline or queue another close; a different request ID is refused.
The one-shot 250ms ticker has a UTC and monotonic deadline, rechecks all policy,
then invokes `IMainFrameModule::RequestCloseEditor()`. A plugin, subeditor or user
confirmation can still veto normal close. `get_editor_close_status` reports the
last local state; `close_requested` is not exit confirmation.

The defer leaves the dispatcher stack but **does not prove that the HTTP ACK was
flushed**. `response_flush_verified` and `process_exit_verified` are always false.
A timeout is not cancellation of an already admitted request. Do not retry with
new IDs, change the host binding, or infer exit from a lost connection. The trusted
launcher must observe the exact original PID/FILETIME/executable exit and registry
removal/invalidation, plus owned input/recording/service cleanup. Until then record
`cleanup_unknown`. A recycled PID is a different process.

For a strict ACK-before-close guarantee, Core must supply a response-completion
callback carrying a live, cancellable request context into the native commit.
This skill does not invent that callback or advertise a synthetic `safe_stop_url`;
Core CLI `stop-instance` remains a separate opt-in transport contract.

Native source retains UE 4.18/4.26 compatibility guards. The standalone sidecar
does not currently expose this Python skill, and cross-version compilation is a
separate gate; this document does not certify a UE 4.x close route.
