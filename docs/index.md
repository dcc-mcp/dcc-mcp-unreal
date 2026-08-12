# Product Requirements Document: dcc-mcp-unreal

**Version**: 0.1.0-draft  
**Status**: Pre-Alpha  
**Author**: DCC-MCP Team  
**Last Updated**: 2026-04-11

> 📖 **Looking for setup instructions?** See the [Installation Guide](installation.md)
> for pip install, uplugin deployment, UE version matrix, and agent-oriented
> quick-start paths. Also see [Unreal Version Compatibility](unreal-version-compatibility.md)
> and [MSVC-Kit Guide](msvc-kit-guide.md).

---

## 1. Executive Summary

`dcc-mcp-unreal` enables AI agents to control Unreal Engine 5 through the
Model Context Protocol (MCP). It embeds a Streamable HTTP MCP server inside
Unreal Engine's Python environment, exposing Editor operations as MCP tools
that any compatible agent (Claude Desktop, Cursor, OpenClaw) can call.

---

## 2. Problem Statement

Unreal Engine 5 has a powerful Python scripting API (`unreal` module) but no
standard way for AI agents to interact with it over a well-defined protocol.
Existing solutions are bespoke integrations that:

- Require custom agent prompting to "know" the Unreal API
- Have no standardized tool schema or error format
- Cannot be composed with tools from other DCCs in a single agent workflow

`dcc-mcp-unreal` solves this by:

1. Exposing Unreal operations as MCP tools with JSON Schema input validation
2. Using the same skill authoring model as `dcc-mcp-maya` — familiar to the team
3. Allowing multi-DCC agent workflows (e.g. model in Maya → import to Unreal)

---

## 3. Goals

### Must Have (v0.1.0)
- Package structure identical to `dcc-mcp-maya`
- `unreal_success` / `unreal_error` / `unreal_from_exception` helpers
- `@with_unreal` decorator for error handling
- `UnrealMcpServer` built on `dcc-mcp-core`'s `DccServerBase`
- At least one working built-in skill (`unreal-actors`)
- Unit tests that run without Unreal Engine installed

### Should Have (v0.2.0)
- 5+ built-in skills covering common editor workflows
- Unreal Editor UI integration (toolbar button)
- Environment variable skill path configuration
- Comprehensive unit test coverage (>80%)

### Nice to Have (v0.3.0+)
- `.uplugin` wrapper for one-click Unreal installation
- Level Sequence / Sequencer MCP tools
- Movie Render Queue integration
- Python mock for `unreal` module in tests

---

## 4. Non-Goals

- **Not a general Unreal Python wrapper** — only MCP-relevant operations
- **Not replacing Unreal's native Python scripting** — this is an MCP bridge
- **Not supporting Unreal Engine < 5.0** — requires Python Editor Script Plugin

---

## 5. User Stories

### Game Developer / Technical Artist

> As a game developer, I want to tell Claude "spawn 10 trees randomly in my
> level" and have it execute the Unreal API calls automatically, so I can
> prototype environments faster.

### Pipeline TD

> As a pipeline TD, I want to build an agent workflow that exports FBX from
> Maya and imports it into Unreal in a single prompt, so I can automate
> asset delivery between DCCs.

### Level Designer

> As a level designer, I want to ask an AI to "list all static mesh actors
> near the player start" and get a structured response I can act on, without
> writing Python manually.

---

## 6. Technical Architecture

### Communication Model

```
Agent (HTTP client)
    │
    │  POST /mcp  (JSON-RPC 2.0)
    ▼
McpHttpServer (Rust axum, OS-assigned instance port)
    │
    │  tools/call → ActionDispatcher
    ▼
subprocess: python skill_script.py
    │
    │  import unreal
    ▼
Unreal Engine Python API (UE5 main thread)
```

### Key Components

| Component | Location | Responsibility |
|-----------|----------|---------------|
| `UnrealMcpServer` | `server.py` | Lifecycle adapter around `DccServerBase` |
| `api.py` | `api.py` | `unreal_success/error/from_exception`, `@with_unreal` |
| Built-in skills | `skills/` | Ready-to-use Unreal operations |
| `dcc-mcp-core` | dependency | HTTP server, skill discovery, JSON-RPC dispatch |

### Skill Execution Flow

```
1. Agent calls tools/call {"name": "unreal_actors__spawn_actor", "arguments": {...}}
2. McpHttpServer receives request
3. ActionDispatcher looks up registered handler for "unreal_actors__spawn_actor"
4. Handler spawns subprocess: python scripts/spawn_actor.py --kwargs='{...}'
5. Script imports unreal, calls Unreal API, returns JSON to stdout
6. ActionDispatcher reads stdout, returns ActionResultModel to agent
```

### Thread Safety

- Unreal Engine's main thread is the only thread allowed to call `unreal` APIs
- Subprocess execution is used (not direct function calls) to respect this constraint
- `UnrealMcpServer` singleton is protected by `threading.Lock`

---

## 7. API Design

### Module-level API

```python
import dcc_mcp_unreal

# Start server
handle = dcc_mcp_unreal.start_server()
print(handle.mcp_url())

# Stop server
dcc_mcp_unreal.stop_server()
```

### Skill authoring helpers

```python
from dcc_mcp_unreal.api import (
    unreal_success,        # Build success dict
    unreal_error,          # Build error dict
    unreal_from_exception, # Build error dict from exception
    with_unreal,           # Decorator: auto error handling
    is_unreal_available,   # Check if unreal module can be imported
    require_unreal,        # Import unreal or raise UnrealNotAvailableError
    get_unreal,            # Import unreal or return None
)
```

### Result format (ActionResultModel-compatible)

```python
{
    "success": True,
    "message": "Spawned actor 'SM_Rock_01' at (0, 0, 100)",
    "prompt": "Use get_actor_transform to verify the position.",
    "error": None,
    "context": {
        "actor_name": "SM_Rock_01",
        "actor_class": "/Script/Engine.StaticMeshActor",
        "location": [0.0, 0.0, 100.0]
    }
}
```

---

## 8. Built-in Skills Roadmap

### v0.1.0 (scaffold)
| Skill | Tool | Description |
|-------|------|-------------|
| unreal-actors | list_actors | List all actors in level |
| unreal-actors | spawn_actor | Spawn actor at world position |

### v0.2.0
| Skill | Tool | Description |
|-------|------|-------------|
| unreal-actors | delete_actor | Delete actor by name |
| unreal-actors | get_actor_transform | Get TRS of actor |
| unreal-actors | set_actor_transform | Set TRS of actor |
| unreal-assets | list_assets | List assets in content browser path |
| unreal-assets | import_asset | Import file into content browser |
| unreal-assets | export_asset | Export asset to file |
| unreal-materials | list_materials | List material instances |
| unreal-materials | set_material_param | Set scalar/vector/texture parameter |
| unreal-level | get_level_info | Get current level name, size, actor count |
| unreal-level | load_level | Load a level by asset path |

### v0.3.0
| Skill | Tool | Description |
|-------|------|-------------|
| unreal-blueprints | get_bp_variable | Read Blueprint variable value |
| unreal-blueprints | set_bp_variable | Set Blueprint variable value |
| unreal-sequencer | list_sequences | List Level Sequences |
| unreal-sequencer | play_sequence | Play a Level Sequence |
| unreal-rendering | render_movie | Trigger Movie Render Queue job |

---

## 9. Testing Strategy

### Unit Tests (no UE required)
- Mock `unreal` module with `unittest.mock`
- Test helper functions (`unreal_success`, `unreal_error`, `@with_unreal`)
- Test server instantiation and configuration
- Test skill path resolution

### Integration Tests (requires UE)
- Marked with `@pytest.mark.e2e`
- Run via `pytest -m e2e` inside Unreal Engine's Python environment
- Test actual `unreal` API calls

### CI Strategy
- Unit tests run on every PR (Ubuntu, Windows, macOS)
- E2E tests run on demand (requires Unreal Engine installation)

---

## 10. Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| `dcc-mcp-core` | >=0.20.0,<1.0.0 | MCP server, skill system, result types |
| `unreal` | bundled with UE5 | Unreal Engine Python API (runtime only) |

Dev dependencies:
- `pytest`, `pytest-cov` — testing
- `ruff` — linting / formatting
- `hatchling` — build system

---

## 11. Security Considerations

- Skill scripts run in subprocesses — isolated from the MCP server process
- `SandboxPolicy` from `dcc-mcp-core` can restrict allowed file paths
- The OS-assigned instance port binds to localhost only; the stable gateway is
  discoverable at `127.0.0.1:9765`
- No authentication in v0.1.0 (localhost-only assumption)
- v0.3.0: consider optional bearer token authentication

---

## 12. Open Questions

1. **Unreal main thread requirement**: Does `subprocess` execution of Unreal Python
   scripts work correctly, or do we need a different dispatch mechanism
   (e.g. Unreal's `tick` callback)?  
   *Hypothesis: Subprocess spawn creates a new UE Python interpreter that has
   main-thread access. Needs validation.*

2. **UE Python version**: UE 5.0 ships Python 3.9; UE 5.4 ships 3.11. Do we
   need version-specific compatibility shims?

3. **Plugin distribution**: Should we ship as a Python package (pip) or as a
   `.uplugin` (Unreal Marketplace / Fab)?  
   *Plan: pip for now, `.uplugin` wrapper in v0.3.0.*

4. **Live reloading**: Can we use `SkillWatcher` hot-reload inside Unreal without
   causing editor instability?
