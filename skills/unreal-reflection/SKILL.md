---
name: unreal-reflection
description: >-
  Secure Unreal Editor UObject discovery, property inspection, policy-gated
  scalar property writes, and policy-gated Blueprint-callable UFunction
  invocation. Use for explicit Unreal reflection workflows, not general scene
  authoring covered by higher-level Unreal skills.
license: MIT
compatibility: Unreal Engine 4.18+ with Python Plugin or Unreal Engine 5.1+ native HTTP bridge
allowed-tools: Bash Read
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: adapter
    search-hint: "Unreal UObject reflection, inspect properties, call UFunction, object discovery"
    tags: "unreal, reflection, uobject, properties, ufunction"
    tools: tools.yaml
---

# Unreal Reflection

Secure UObject reflection for Unreal Engine Editor. Discover objects in the
current level, inspect their properties and functions, read/write property
values (policy-gated), and call Blueprint-callable UFunctions (policy-gated).

## Security Model

All operations are **fail-closed**: private names (`_`-prefixed), engine
internals (Default__*, GameMode, PlayerController, etc.), lifecycle functions
(BeginPlay, Tick, Destroy), and RPC functions (Server_*, Client_*, Multicast_*)
are permanently denied — regardless of the active policy.

Property writes and UFunction calls are **disabled by default**. Enable them
with `DCC_MCP_UNREAL_ALLOW_WRITE=1` and `DCC_MCP_UNREAL_ALLOW_EXECUTE=1`.

All mutating operations execute on the editor **main thread** (GameThread).

The native C++ HTTP bridge accepts scalar property values and zero-argument
UFunctions only. Calls that need structured values or function arguments must
run through Unreal Python direct mode; the native bridge fails closed instead
of discarding unsupported input. `timeout_ms` bounds the client request, but an
already-running GameThread UFunction cannot be interrupted safely.

## Tools

<!-- Tools are declared in tools.yaml -->

## Environment

- `DCC_MCP_UNREAL_ALLOW_WRITE` — Set to "1" to enable property writes.
- `DCC_MCP_UNREAL_ALLOW_EXECUTE` — Set to "1" to enable UFunction calls.
- `DCC_MCP_UNREAL_SKILL_PATHS` — Extra skill directories.

## Compatibility

- UE 4.18+ (Python Plugin required)
- UE 5.x (Python Plugin or C++ plugin HTTP bridge)
